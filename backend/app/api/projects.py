"""API экранов: проекты, анкета, модуль коллеги (гипотезы, сценарий, офферы, дизайн), интервью, стенограмма,
инсайты, валидация, отчёт. Представление проекта отдаётся одним запросом в форме типов фронтенда
(frontend/src/domain/types.ts), чтобы страницы не собирали его по частям. Долгие операции — задачи воркера.
"""
import asyncio
import json
import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import reports
from app.core.config import get_settings
from app.core.db import get_db
from app.design import service as design
from app.models import Claim, DesignStage, Insight, Interview, LlmCall, Project, ProjectJob, StenogramRow, Turn

router = APIRouter(prefix="/projects", tags=["projects"])
iv_router = APIRouter(prefix="/interviews", tags=["projects"])
Db = Annotated[AsyncSession, Depends(get_db)]
MAX_BYTES = 2 * 1024**3  # макет 08: до 2 ГБ
AUDIO_EXT = {"mp3", "wav", "mp4", "mov", "m4a", "ogg", "webm", "aac", "flac"}
REQUIRED = ["product", "role", "job", "situation", "problem", "losses", "function", "outcome", "alternatives", "decision"]
SLOT_LETTER = {"Б": "role", "Б1": "job", "Б2": "situation", "В": "problem", "В1": "losses", "Г": "function",
               "Д": "outcome", "Д1": "effect", "Е": "problem", "А": "product"}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября",
          "декабря"]


def mmss(sec: float | None) -> str:
    if sec is None:
        return ""
    s = int(sec)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def human_date(d: datetime) -> str:
    local = d.astimezone()
    if local.date() == datetime.now(UTC).astimezone().date():
        return f"Сегодня, {local:%H:%M}"
    return f"{local.day} {MONTHS[local.month - 1]}, {local:%H:%M}"


async def _project(db: AsyncSession, project_id: str) -> Project:
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Проект не найден")
    return p


async def _enqueue(request: Request, fn: str, *args: Any) -> None:
    await request.app.state.arq.enqueue_job(fn, *args)


def interview_job_id(interview_id: int) -> str:
    """Один id задачи на интервью: arq не примет вторую задачу с тем же id, пока первая в очереди или выполняется
    (15.11.2026 повторные нажатия «Повторить» поставили до 9 полных обработок одной записи)."""
    return f"interview:{interview_id}"


async def enqueue_interview(request: Request, fn: str, interview_id: int) -> bool:
    job = await request.app.state.arq.enqueue_job(fn, interview_id, _job_id=interview_job_id(interview_id))
    return job is not None


async def _job(db: AsyncSession, project_id: str, kind: str) -> ProjectJob | None:
    return (await db.scalars(select(ProjectJob).where(ProjectJob.project_id == project_id,
                                                      ProjectJob.kind == kind))).first()


async def _start(request: Request, db: AsyncSession, project_id: str, kind: str, fn: str) -> None:
    """Ставит задачу проекта, если такая же ещё не идёт. «Идёт обработка» видно сразу, до старта воркера."""
    row = await _job(db, project_id, kind)
    if row and row.status == "running":
        return
    if row is None:
        db.add(ProjectJob(project_id=project_id, kind=kind, status="running"))
    else:
        row.status, row.error = "running", None
    await db.commit()
    await _enqueue(request, fn, project_id)


# ================================================================== список проектов
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectPatch(BaseModel):
    name: str | None = None
    pinned: bool | None = None
    status: str | None = Field(None, pattern="^(in_progress|done)$")


async def step_index(db: AsyncSession, p: Project) -> int:
    """Текущий шаг 0..9 (порядок STUDY_STEPS фронтенда)."""
    if p.status == "done":
        return 9
    if await db.scalar(select(func.count()).select_from(Insight).where(Insight.project_id == p.id)):
        return 8
    if await db.scalar(select(func.count()).select_from(StenogramRow).where(StenogramRow.project_id == p.id)):
        return 7
    if await db.scalar(select(func.count()).select_from(Interview).where(Interview.project_id == p.id,
                                                                         Interview.status == "processed")):
        return 6
    if p.locked:
        return 5
    stages = set((await db.scalars(select(DesignStage.stage).where(DesignStage.project_id == p.id))).all())
    return 4 if "design" in stages else 2 if "scenarios" in stages else 1 if "segments" in stages else 0


async def project_card(db: AsyncSession, p: Project) -> dict[str, Any]:
    n_iv = await db.scalar(select(func.count()).select_from(Interview).where(Interview.project_id == p.id)) or 0
    return dict(id=p.id, name=p.name, status=p.status, stepIndex=await step_index(db, p),
                segments=len(p.selection.get("segments", [])), interviews=n_iv,
                updatedAt="Обновлено " + human_date(p.updated_at).replace("Сегодня", "сегодня"), pinned=p.pinned)


@router.get("")
async def list_projects(db: Db) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Project).order_by(Project.pinned.desc(), Project.updated_at.desc()))).all()
    return [await project_card(db, p) for p in rows]


@router.post("", status_code=201)
async def create_project(body: ProjectIn, db: Db) -> dict[str, Any]:
    p = Project(id=uuid.uuid4().hex[:12], name=body.name.strip(), context={}, selection={})
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return await project_card(db, p)


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectPatch, db: Db) -> dict[str, Any]:
    p = await _project(db, project_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    await db.commit()
    await db.refresh(p)
    return await project_card(db, p)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: Db) -> Response:
    await db.delete(await _project(db, project_id))
    await db.commit()
    return Response(status_code=204)


# ================================================================== анкета и модуль коллеги
class ContextIn(BaseModel):
    values: dict[str, str]


@router.put("/{project_id}/context")
async def save_context(project_id: str, body: ContextIn, db: Db) -> dict[str, str]:
    p = await _project(db, project_id)
    if p.locked:
        raise HTTPException(409, "Интервью уже идут по этой анкете — она зафиксирована")
    p.context = dict(body.values)
    if p.context.get("product") and p.name == "Новое исследование":
        p.name = p.context["product"][:200]
    await db.commit()
    return {"status": "saved"}


@router.post("/{project_id}/hypotheses/generate", status_code=202)
async def generate_hypotheses(project_id: str, request: Request, db: Db) -> dict[str, str]:
    p = await _project(db, project_id)
    missing = [k for k in REQUIRED if not (p.context.get(k) or "").strip()]
    if missing:
        raise HTTPException(422, {"missing": missing})
    if p.locked:
        raise HTTPException(409, "Дизайн зафиксирован: интервью уже загружаются")
    await _start(request, db, project_id, "hypotheses", "design_hypotheses")
    return {"status": "running"}


class SelectionIn(BaseModel):
    segments: list[str]
    values: dict[str, list[str]]  # SEG01 → ["SEG01-H01"]


@router.put("/{project_id}/selection")
async def save_selection(project_id: str, body: SelectionIn, db: Db) -> dict[str, str]:
    p = await _project(db, project_id)
    if p.locked:
        raise HTTPException(409, "Дизайн зафиксирован: интервью уже идут по выбранным гипотезам")
    p.selection = {"segments": body.segments,
                   "values": {seg: [v.split("-")[-1] for v in vs] for seg, vs in body.values.items()}}
    await db.commit()
    return {"status": "saved"}


@router.post("/{project_id}/scenario/generate", status_code=202)
async def generate_scenario(project_id: str, request: Request, db: Db) -> dict[str, str]:
    p = await _project(db, project_id)
    if p.locked:
        raise HTTPException(409, "Дизайн зафиксирован: интервью уже загружаются")
    if not p.selection.get("segments"):
        raise HTTPException(422, "Выберите сегменты и гипотезы ценности")
    await _start(request, db, project_id, "scenario", "design_scenario")
    return {"status": "running"}


async def _lock(request: Request, db: AsyncSession, project_id: str) -> None:
    p = await _project(db, project_id)
    if p.locked:
        return
    try:
        await design.lock_design(project_id)
    except design.DesignError as e:
        raise HTTPException(409, str(e)) from e
    await _start(request, db, project_id, "prepare", "prepare_project")


@router.post("/{project_id}/lock")
async def lock(project_id: str, request: Request, db: Db) -> dict[str, str]:
    """Фиксация дизайна перед интервью: выбранные гипотезы и сценарий → модуль анализа, затем шаг 0 и шаг 3а."""
    await _lock(request, db, project_id)
    return {"status": "locked"}


# ================================================================== интервью
@router.post("/{project_id}/interviews", status_code=201)
async def upload_interview(project_id: str, request: Request, db: Db, file: Annotated[UploadFile, File()],
                           segment: Annotated[str, Form()]) -> dict[str, Any]:
    p = await _project(db, project_id)
    if segment not in p.selection.get("segments", []):
        raise HTTPException(422, "Сегмент не выбран в дизайне исследования")
    name = file.filename or "interview"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in AUDIO_EXT:
        raise HTTPException(415, "Формат не поддерживается: mp3, wav, mp4, mov, m4a")
    size = file.size or 0  # Starlette уже сбросил тело во временный файл — в память целиком не читаем
    if size > MAX_BYTES:
        raise HTTPException(413, "Файл больше 2 ГБ")
    await _lock(request, db, project_id)
    codes = (await db.scalars(select(Interview.respondent_code).where(Interview.project_id == project_id))).all()
    nums = [int(m.group(1)) for c in codes if (m := re.fullmatch(r"R(\d+)", c))]
    code = f"R{max(nums, default=0) + 1:02d}"
    key = f"interviews/{project_id}/{uuid.uuid4().hex}-{name}"
    await asyncio.to_thread(request.app.state.storage.put_object, get_settings().minio_bucket, key, file.file,
                            length=-1, part_size=16 * 1024**2,
                            content_type=file.content_type or "application/octet-stream")
    iv = Interview(project_id=project_id, segment_code=segment, respondent_code=code, filename=name, object_key=key,
                   size_bytes=size)
    db.add(iv)
    p.updated_at = datetime.now(UTC)
    await db.commit()
    await enqueue_interview(request, "transcribe_and_process", iv.id)
    return {"id": str(iv.id), "respondentId": code}


@iv_router.delete("/{interview_id}", status_code=204)
async def delete_interview(interview_id: int, request: Request, db: Db) -> Response:
    iv = await db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, "Интервью не найдено")
    key = iv.object_key
    await db.delete(iv)
    await db.commit()
    await asyncio.to_thread(request.app.state.storage.remove_object, get_settings().minio_bucket, key)
    return Response(status_code=204)


@iv_router.post("/{interview_id}/retry", status_code=202)
async def retry_interview(interview_id: int, request: Request, db: Db) -> dict[str, str]:
    iv = await db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, "Интервью не найдено")
    has_turns = await db.scalar(select(func.count()).select_from(Turn).where(Turn.interview_id == iv.id))
    if not await enqueue_interview(request, "process_interview_job" if has_turns else "transcribe_and_process", iv.id):
        raise HTTPException(409, "Запись уже обрабатывается или стоит в очереди")
    return {"status": "queued"}


@iv_router.get("/{interview_id}/transcript")
async def transcript(interview_id: int, db: Db) -> list[dict[str, Any]]:
    turns = (await db.scalars(select(Turn).where(Turn.interview_id == interview_id).order_by(Turn.turn_index))).all()
    return [dict(index=t.turn_index, time=mmss(t.start_sec), seconds=t.start_sec, speaker=t.speaker_role, text=t.text)
            for t in turns]


@iv_router.get("/{interview_id}/media")
async def media(interview_id: int, request: Request, db: Db) -> Response:
    """Запись для плеера через API (MinIO наружу не публикуется). Поддерживает Range (206): без него браузер не
    перематывает запись — ни ползунком, ни переходом «Открыть запись на этом месте» из цитат."""
    iv = await db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, "Интервью не найдено")
    storage, bucket = request.app.state.storage, get_settings().minio_bucket
    size = iv.size_bytes or (await asyncio.to_thread(storage.stat_object, bucket, iv.object_key)).size
    start, end = 0, size - 1
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("range", "").strip())
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else min(start + 4 * 1024**2 - 1, size - 1)
        else:  # bytes=-N — последние N байт
            start = max(0, size - int(m.group(2)))
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    obj = await asyncio.to_thread(storage.get_object, bucket, iv.object_key, offset=start, length=end - start + 1)
    try:
        data = await asyncio.to_thread(obj.read)
    finally:
        obj.close()
        obj.release_conn()
    ext = iv.filename.rsplit(".", 1)[-1].lower()
    mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "mp4": "video/mp4", "mov": "video/quicktime",
            "ogg": "audio/ogg", "webm": "audio/webm"}.get(ext, "application/octet-stream")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600",
               "Expires": (datetime.now(UTC) + timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")}
    if m and (m.group(1) or m.group(2)):
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return Response(data, status_code=206, media_type=mime, headers=headers)
    return Response(data, media_type=mime, headers=headers)


# ================================================================== анализ: стенограмма, инсайты, переформулировка
@router.post("/{project_id}/stenogram/run", status_code=202)
async def run_stenogram(project_id: str, request: Request, db: Db) -> dict[str, str]:
    await _project(db, project_id)
    await _start(request, db, project_id, "stenogram", "stenogram_job")
    return {"status": "running"}


@router.post("/{project_id}/insights/run", status_code=202)
async def run_insights(project_id: str, request: Request, db: Db) -> dict[str, str]:
    await _project(db, project_id)
    await _start(request, db, project_id, "insights", "insights_job")
    return {"status": "running"}


@router.post("/{project_id}/reformulate", status_code=202)
async def reformulate(project_id: str, request: Request, db: Db) -> dict[str, str]:
    await _project(db, project_id)
    await _start(request, db, project_id, "reformulate", "reformulate_job")
    return {"status": "running"}


class QuoteIn(BaseModel):
    respondentId: str
    time: str = ""
    text: str


class InsightIn(BaseModel):
    """Ручное добавление и правка инсайта (экраны 10.2, 10.3)."""
    segmentId: str
    hypothesisKind: str = Field(pattern="^(segment|value)$")
    slot: str
    relation: str = Field(pattern="^(extends|contradicts)$")
    title: str
    expected: str
    observed: str
    quotes: list[QuoteIn] = []
    comment: str | None = None


def _insight_data(body: InsightIn, base: dict[str, Any] | None = None) -> dict[str, Any]:
    letter = {v: k for k, v in SLOT_LETTER.items() if k != "Е"}.get(body.slot, "")
    d = dict(base or {})
    d.update(title=body.title, insight=d.get("insight") or body.title, expected=body.expected, observed=body.observed,
             affected_slots=[letter] if letter else [], slot=body.slot, hypothesis_kind=body.hypothesisKind,
             relation_expert="Опровергает" if body.relation == "contradicts" else "Дополняет",
             evidence=[dict(respondent_id=q.respondentId, quote=q.text, time_text=q.time, role="supports")
                       for q in body.quotes])
    return d


@router.post("/{project_id}/insights", status_code=201)
async def add_insight(project_id: str, body: InsightIn, db: Db) -> dict[str, str]:
    await _project(db, project_id)
    n = await db.scalar(select(func.count()).select_from(Insight).where(Insight.project_id == project_id)) or 0
    ins = Insight(project_id=project_id, segment_code=body.segmentId, insight_code=f"{body.segmentId}-USR-{n + 1:02d}",
                  source="user", level="candidate", accepted=True, data=_insight_data(body),
                  comments=[{"text": body.comment}] if body.comment else [])
    db.add(ins)
    await db.commit()
    return {"id": str(ins.id)}


@router.put("/{project_id}/insights/{insight_id}")
async def edit_insight(project_id: str, insight_id: int, body: InsightIn, db: Db) -> dict[str, str]:
    ins = await db.get(Insight, insight_id)
    if ins is None or ins.project_id != project_id:
        raise HTTPException(404, "Инсайт не найден")
    ins.data = _insight_data(body, ins.data)
    ins.source = "user"  # правка человека: повторный поиск инсайтов её не перезапишет
    if body.comment:
        ins.comments = [*ins.comments, {"text": body.comment}]
    await db.commit()
    return {"status": "saved"}


# ================================================================== выгрузки
@router.get("/{project_id}/export/{kind}")
async def export(project_id: str, kind: str, db: Db, fmt: str = "docx") -> Response:
    """kind: report | design | scenario | package (JSON пакета результатов); fmt: docx | md."""
    await _project(db, project_id)
    if kind == "package":
        body = json.dumps(await reports.results_package(project_id), ensure_ascii=False, indent=1).encode()
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{project_id}-package.json"'})
    if kind not in ("report", "design", "scenario"):
        raise HTTPException(404, "Неизвестная выгрузка")
    md = await reports.markdown(project_id, kind)
    if fmt == "md":
        return Response(md.encode(), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{project_id}-{kind}.md"'})
    return Response(reports.docx_from_markdown(md),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="{project_id}-{kind}.docx"'})


# ================================================================== представление проекта для экранов
@router.get("/{project_id}/view")
async def view(project_id: str, db: Db) -> dict[str, Any]:
    p = await _project(db, project_id)
    st = {r.stage: r.response for r in (await db.scalars(select(DesignStage).where(
        DesignStage.project_id == project_id))).all()}
    jobs = {j.kind: dict(status=j.status, error=j.error) for j in (await db.scalars(select(ProjectJob).where(
        ProjectJob.project_id == project_id))).all()}
    seg_ids = list(p.selection.get("segments", []))

    # 04: варианты модуля коллеги
    seg_variants = [variant(x, "segment", x["segment_id"], n)
                    for n, x in enumerate(st.get("segments", {}).get("segments", []), 1)]
    hyp_rows = st.get("hypotheses", {}).get("hypotheses", [])
    value_variants = [variant(x, "value", x["segment_id"],
                              [h["hypothesis_id"] for h in hyp_rows if h["segment_id"] == x["segment_id"]]
                              .index(x["hypothesis_id"]) + 1) for x in hyp_rows]

    # 05–07
    checks = await reports.question_slots(project_id)
    scenario = {sc["segment_id"]: scenario_sections(sc, checks.get(sc["segment_id"], {}))
                for sc in st.get("scenarios", {}).get("scenarios", [])}
    offers = st.get("offers", {})
    recruiting = {o["segment_id"]: recruiting_plan(o, offers.get("fixed_channels")) for o in offers.get("offers", [])}
    planned = sum(5 if o.get("interview_count") == "5" else 15 for o in offers.get("offers", [])) or 15

    # 08
    ivs = (await db.scalars(select(Interview).where(Interview.project_id == project_id).order_by(Interview.id.desc()))).all()
    claims_n = {k: v for k, v in (await db.execute(select(Claim.interview_id, func.count()).join(Interview).where(
        Interview.project_id == project_id).group_by(Claim.interview_id))).tuples().all()}

    # 09
    sten: dict[str, list[dict[str, Any]]] = {}
    for r in (await db.scalars(select(StenogramRow).where(StenogramRow.project_id == project_id)
                               .order_by(StenogramRow.question_id))).all():
        sten.setdefault(r.segment_code, []).append(dict(
            questionId=r.question_id, summary=r.summary, answers={k: v["text"] for k, v in r.answers.items()},
            times={k: mmss(v.get("time")) for k, v in r.answers.items()}))

    tokens = await db.scalar(select(func.coalesce(func.sum(LlmCall.tokens_in + LlmCall.tokens_out), 0)).where(
        LlmCall.project_id == project_id)) or 0
    return dict(
        id=p.id, name=p.name, status=p.status, stepIndex=await step_index(db, p), locked=p.locked,
        updatedAt=human_date(p.updated_at), context=p.context, jobs=jobs,
        segmentVariants=seg_variants, valueVariants=value_variants, selectedSegments=seg_ids,
        selectedValues={seg: [f"{seg}-{h}" for h in hs] for seg, hs in p.selection.get("values", {}).items()},
        segmentLabel={s: f"Сегмент {i + 1}" for i, s in enumerate(seg_ids)},
        generationNote=" ".join(x for x in (st.get("segments", {}).get("message"),
                                            st.get("hypotheses", {}).get("message")) if x),
        scenario=scenario, recruiting=recruiting, design=st.get("design", {}).get("product_description"),
        plannedInterviews=planned,
        respondents=[dict(id=iv.respondent_code, code=iv.respondent_code, name=iv.filename.rsplit(".", 1)[0][:40],
                          role="", segmentId=iv.segment_code) for iv in reversed(ivs)],
        interviews=[interview_card(iv, claims_n.get(iv.id, 0)) for iv in ivs],
        stenogram=sten,
        insights=[insight_card(i) for i in (await db.scalars(select(Insight).where(Insight.project_id == project_id)
                                                             .order_by(Insight.segment_code, Insight.id))).all()],
        validation=await reports.validation(project_id),
        reformulated=reports.reformulated(st, p.selection),
        tokensUsed=int(tokens),
    )


def variant(x: dict[str, Any], kind: str, seg: str, n: int) -> dict[str, Any]:
    check = x.get("check") or {"passed": True, "failed_criteria": []}
    hid = x["segment_id"] if kind == "segment" else f"{seg}-{x['hypothesis_id']}"
    return dict(id=hid, kind=kind, segmentId=seg, variantNo=n, text=x.get("text", ""),
                lines=design.slot_lines(x.get("elements"), x.get("text", ""), kind),
                check=dict(passed=bool(check.get("passed")),
                           reasons=[f["reason"] for f in check.get("failed_criteria") or []]))


def scenario_sections(sc: dict[str, Any], checks: dict[str, list[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in sc.get("items", []):
        title = it.get("section") or "Вопросы"
        if not out or out[-1]["title"] != title:
            out.append(dict(id=f"s{len(out) + 1}", title=title, questions=[]))
        qid = f"Q{it['row_no']:02d}"
        out[-1]["questions"].append(dict(id=qid, topic=it.get("topic"), text=design.plain_question(it["question"]),
                                         hint=it.get("hint"), checks=checks.get(qid, [])))
    return out


def recruiting_plan(o: dict[str, Any], fixed: dict[str, Any] | None) -> dict[str, Any]:
    count = o.get("interview_count")
    return dict(
        whom=o.get("who_to_find", ""),
        interviewsTarget=f"{count} на сегмент" if count else "",
        interviewsNote=o.get("interview_count_note"),
        criteria=o.get("selection_criteria", []),
        filterQuestions=[design.plain_question(q) for q in o.get("screening_questions", [])],
        channels=[dict(order="Сначала" if s["step_no"] == 1 else "Затем", channel=s["channel"],
                       offer="personal" if s["offer_type"] == "personal" else "seed") for s in o.get("search_sequence", [])],
        offers=dict(personal=o.get("personal_offer", ""), seed=o.get("seeding_offer", "")),
        recommended=[dict(name=c["title"], description=c["description"], url=c.get("url") or "")
                     for c in o.get("channel_recommendations", [])],
        fixed=dict(caption=(fixed or {}).get("caption", ""),
                   channels=[dict(name=c["title"], description=c["description"], url=c["url"])
                             for c in (fixed or {}).get("channels", [])]),
    )


STEPS = ["Расшифровываем запись", "Разбираем ответы", "Сверяем с гипотезами"]
TRANSCRIBE_TYPICAL_SEC = 240  # Nexara не сообщает прогресс; 14–15.11.2026 записи 18–60 мин шли 3–7 мин


def interview_progress(iv: Interview) -> tuple[int | None, str | None]:
    """Простой индикатор экрана 08: шаг N из 3 и общий процент. Расшифровка — оценка по времени (плавно
    подходит к концу шага, но не достигает его), разбор и сверка — по реально пройденным подшагам ИГ1."""
    from app.ig1.pipeline import PROGRESS

    if iv.status in ("uploaded", "transcribing"):
        started = iv.stage_started_at or iv.created_at
        elapsed = max(0.0, (datetime.now(UTC) - started).total_seconds())
        step, frac = 0, min(0.95, 1 - math.exp(-elapsed / TRANSCRIBE_TYPICAL_SEC))
    elif iv.status == "transcribed":
        step, frac = 1, 0.0
    elif iv.status == "processing":
        p, edge = iv.stage_progress or 0.0, PROGRESS["claims"]
        step, frac = (1, p / edge) if p < edge else (2, (p - edge) / (1 - edge))
    else:
        return None, None
    return round(100 * (step + frac) / len(STEPS)), f"Шаг {step + 1} из {len(STEPS)} · {STEPS[step]}"


def interview_card(iv: Interview, n_claims: int) -> dict[str, Any]:
    status = {"uploaded": "transcribing", "transcribing": "transcribing", "transcribed": "processing",
              "processing": "processing", "processed": "transcribed", "error": "error"}[iv.status]
    ext = iv.filename.rsplit(".", 1)[-1].lower() if "." in iv.filename else ""
    progress, stage = interview_progress(iv)
    return dict(id=str(iv.id), respondentId=iv.respondent_code, segmentId=iv.segment_code, fileType=ext,
                fileName=iv.filename, durationMin=round((iv.duration_sec or 0) / 60),
                sizeMb=round(iv.size_bytes / 1024**2, 1), status=status, error=iv.error, claims=n_claims,
                progress=progress, stageLabel=stage, recordedAt=human_date(iv.created_at))


def insight_card(i: Insight) -> dict[str, Any]:
    d = i.data
    slots = [SLOT_LETTER.get(str(x).strip("{} "), "") for x in d.get("affected_slots") or []]
    slot = d.get("slot") or next((x for x in slots if x), "problem")
    kind = d.get("hypothesis_kind") or ("value" if re.search(r"-?H\d+", str(d.get("hypothesis") or "")) else "segment")
    quotes = [dict(respondentId=e.get("respondent_id", ""), time=e.get("time_text") or mmss(e.get("time")),
                   text=e.get("quote") or "", counter=e.get("role") == "counterexample")
              for e in d.get("evidence") or [] if e.get("quote")]
    resp = d.get("respondents") or {}
    return dict(id=str(i.id), code=i.insight_code, segmentId=i.segment_code, hypothesisKind=kind, slot=slot,
                relation="contradicts" if "Опроверг" in str(d.get("relation_expert")) else "extends",
                title=d.get("title") or d.get("insight") or "", insight=d.get("insight") or "",
                expected=d.get("expected") or "", observed=d.get("observed") or "",
                explanation=d.get("explanation") or "", quotes=quotes, comments=len(i.comments),
                level=i.level, accepted=i.accepted, source=i.source,
                nSupporting=resp.get("n_supporting"), nSegment=resp.get("n_segment"),
                boundaries=d.get("boundaries") or [],
                actions=[a.get("text") for a in d.get("suggested_actions") or [] if isinstance(a, dict)])
