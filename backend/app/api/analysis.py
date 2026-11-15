"""API модуля анализа интервью: проект (анкета, гипотезы по слотам, план), подготовка (шаг 0, область, шаг 3а),
загрузка записей (MinIO) → расшифровка Nexara → обработка (шаги 2–6) → результаты ИГ2.
Долгие операции ставятся в очередь arq и выполняются воркером."""
import asyncio
import io
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.ig1.pipeline import results as ig2_results
from app.models import Claim, Hypothesis, Interview, PlanQuestion, Project, ProjectDomain, Subdomain, Turn

router = APIRouter(prefix="/analysis", tags=["analysis"])
MAX_BYTES = 3 * 1024**3  # лимит Nexara


class SlotLineIn(BaseModel):
    slot: str
    lead: str | None = None
    text: str


class HypothesisIn(BaseModel):
    segment_code: str
    code: str
    kind: str = Field(pattern="^(segment|value)$")
    lines: list[SlotLineIn]


class QuestionIn(BaseModel):
    segment_code: str
    question_id: str
    section: str = ""
    text: str
    checks: list[str] = []


class ProjectIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]{2,64}$")
    name: str
    context: dict[str, str]
    hypotheses: list[HypothesisIn]
    plan: list[QuestionIn]


Db = Annotated[AsyncSession, Depends(get_db)]


async def _enqueue(request: Request, fn: str, *args: Any) -> str:
    # задачи интервью — с постоянным id, как в app/api/projects.py: не больше одной на запись
    kw = {"_job_id": f"interview:{args[0]}"} if fn in ("transcribe_and_process", "process_interview_job") else {}
    job = await request.app.state.arq.enqueue_job(fn, *args, **kw)
    return job.job_id if job else ""


@router.put("/projects")
async def upsert_project(body: ProjectIn, db: Db) -> dict[str, Any]:
    """Создаёт или заменяет проект: анкета А–Ж, выбранные гипотезы (по слотам) и план интервью."""
    project = await db.get(Project, body.id)
    if project is None:
        project = Project(id=body.id, name=body.name, context=body.context)
        db.add(project)
    else:
        project.name, project.context = body.name, body.context
        await db.execute(delete(Hypothesis).where(Hypothesis.project_id == body.id))
        await db.execute(delete(PlanQuestion).where(PlanQuestion.project_id == body.id))
    await db.flush()
    for h in body.hypotheses:
        db.add(Hypothesis(project_id=body.id, segment_code=h.segment_code, code=h.code, kind=h.kind,
                          lines=[x.model_dump() for x in h.lines]))
    for q in body.plan:
        db.add(PlanQuestion(project_id=body.id, **q.model_dump()))
    await db.commit()
    return {"id": body.id, "hypotheses": len(body.hypotheses), "questions": len(body.plan)}


@router.post("/projects/{project_id}/prepare")
async def prepare(project_id: str, request: Request, db: Db) -> dict[str, str]:
    """Шаг 0 (компоненты) → область → шаг 3а для всех сегментов — одной фоновой задачей."""
    if await db.get(Project, project_id) is None:
        raise HTTPException(404, "Проект не найден")
    return {"job_id": await _enqueue(request, "prepare_project", project_id)}


@router.get("/projects/{project_id}/domain")
async def domain(project_id: str, db: Db) -> list[dict[str, Any]]:
    q = (select(ProjectDomain, Subdomain).join(Subdomain, ProjectDomain.subdomain_code == Subdomain.code)
         .where(ProjectDomain.project_id == project_id))
    return [dict(code=sd.code, name=sd.name, industry=sd.industry_name, primary=pd.is_primary,
                 rationale=pd.rationale, confidence=pd.confidence, added_by=sd.added_by)
            for pd, sd in (await db.execute(q)).all()]


@router.post("/projects/{project_id}/interviews", status_code=201)
async def upload_interview(
    project_id: str, request: Request, db: Db,
    file: Annotated[UploadFile, File()],
    segment_code: Annotated[str, Form()],
    respondent_code: Annotated[str, Form()],
) -> dict[str, Any]:
    """Загрузка записи в MinIO и постановка в очередь: расшифровка Nexara → обработка шагов 2–6."""
    if await db.get(Project, project_id) is None:
        raise HTTPException(404, "Проект не найден")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Файл больше 3 ГБ")
    name = file.filename or "interview"
    key = f"interviews/{project_id}/{uuid.uuid4().hex}-{name}"
    storage = request.app.state.storage
    await asyncio.to_thread(storage.put_object, get_settings().minio_bucket, key, io.BytesIO(data), len(data),
                            content_type=file.content_type or "application/octet-stream")
    iv = Interview(project_id=project_id, segment_code=segment_code, respondent_code=respondent_code,
                   filename=name, object_key=key, size_bytes=len(data))
    db.add(iv)
    await db.commit()
    return {"id": iv.id, "job_id": await _enqueue(request, "transcribe_and_process", iv.id)}


@router.post("/interviews/{interview_id}/process")
async def reprocess(interview_id: int, request: Request, db: Db) -> dict[str, str]:
    """Повторная обработка шагов 2–6 по уже расшифрованной записи."""
    if await db.get(Interview, interview_id) is None:
        raise HTTPException(404, "Интервью не найдено")
    return {"job_id": await _enqueue(request, "process_interview_job", interview_id)}


@router.get("/interviews/{interview_id}")
async def interview(interview_id: int, db: Db) -> dict[str, Any]:
    iv = await db.get(Interview, interview_id)
    if iv is None:
        raise HTTPException(404, "Интервью не найдено")
    turns = (await db.scalars(select(Turn).where(Turn.interview_id == iv.id).order_by(Turn.turn_index))).all()
    n_claims = await db.scalar(select(func.count()).select_from(Claim).where(Claim.interview_id == iv.id))
    return dict(
        id=iv.id, status=iv.status, error=iv.error, segment=iv.segment_code, respondent=iv.respondent_code,
        duration_sec=iv.duration_sec, claims=n_claims,
        turns=[dict(turn_index=t.turn_index, role=t.speaker_role, speaker=t.speaker_label, start=t.start_sec,
                    text=t.text, text_anon=t.text_anon, question_ids=t.question_ids, off_plan=t.off_plan)
               for t in turns],
    )


@router.get("/interviews/{interview_id}/claims")
async def interview_claims(interview_id: int, db: Db) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Claim).where(Claim.interview_id == interview_id).order_by(Claim.turn_index))).all()
    return [dict(claim_id=c.claim_id, turn_index=c.turn_index, claim_text=c.claim_text, source_quote=c.source_quote,
                 quote_ok=c.quote_ok, subject=c.subject, kind=c.kind, period=c.period, question_ids=c.question_ids)
            for c in rows]


@router.get("/projects/{project_id}/results")
async def project_results(project_id: str) -> list[dict[str, Any]]:
    """ИГ2: статусы компонентов и X % по каждой выбранной гипотезе."""
    return await ig2_results(project_id)
