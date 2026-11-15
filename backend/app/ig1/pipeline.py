"""Оркестрация модуля анализа интервью: шаг 0 → область → шаг 3а → (по каждому интервью) 1 → 2 → 3б → 4 → 5 → 6 → ИГ2.

Каждая функция — самостоятельная фоновая задача (воркер arq) с собственной сессией БД.
"""
import asyncio
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.storage import make_client
from app.ig1 import domains as D
from app.ig1 import ig2
from app.ig1 import prompts as P
from app.ig1.anonymize import anonymize_names
from app.ig1.domain_catalog import CATALOG
from app.ig1.llm import BATCH5, LOW_REASONING, Llm, LlmError
from app.ig1.nexara import NexaraError, create_job, segments_to_turns, wait_job
from app.models import (
    Claim,
    Component,
    Hypothesis,
    Interview,
    LlmCall,
    Pair,
    PlanQuestion,
    Project,
    ProjectDomain,
    Subdomain,
    Turn,
)

# Способ проверки по слоту: функция и эффект проблемным интервью не проверяются (пилот)
VERIFICATION = {"function": "pilot", "effect": "timed_pilot"}
SKIP_SLOTS = {"product"}  # название продукта — не проверяемое условие
# Доля обработки (статус processing) после подшагов; шаг 5 — остаток, пропорционально пакетам.
# Граница «разбор ответов» / «сверка с гипотезами» для пользователя — PROGRESS["claims"].
PROGRESS = {"prepared": 0.08, "matched": 0.3, "claims": 0.55}
# Пакетов шага 5 одного интервью одновременно; воркер обрабатывает до 4 интервью → до 16 запросов к Cloud.ru.
# Ответы 429 / 5xx при перегрузке подхватывают повторы клиента (NET_RETRY_PAUSES в app/ig1/llm.py).
STEP5_CONCURRENCY = 4


def _llm(project_id: str | None, interview_id: int | None = None) -> Llm:
    async def log(step: str, model: str, tin: int, tout: int, sec: float, ok: bool, err: str | None) -> None:
        async with SessionLocal() as s:
            s.add(LlmCall(project_id=project_id, interview_id=interview_id, step=step, model=model,
                          tokens_in=tin, tokens_out=tout, seconds=round(sec, 2), ok=ok, error=err))
            await s.commit()
    return Llm(log)


def _statement(line: dict[str, Any]) -> str:
    return " ".join(x for x in (line.get("lead"), line.get("text")) if x).strip(" ,.")


# ------------------------------------------------------------------ шаг 0: компоненты гипотез
async def prepare_components(project_id: str) -> int:
    async with SessionLocal() as s:
        project = await s.get(Project, project_id)
        hyps = (await s.scalars(select(Hypothesis).where(Hypothesis.project_id == project_id, Hypothesis.selected))).all()
        raw = []
        for h in hyps:
            for line in h.lines:
                if line["slot"] in SKIP_SLOTS:
                    continue
                raw.append(dict(component_id=f"{h.code}:{line['slot']}", hypothesis_ids=[h.code], slot=line["slot"],
                                statement=_statement(line), verification_method=VERIFICATION.get(line["slot"], "interview")))
        llm = _llm(project_id)
        try:
            obj = await llm.call("0", P.SYSTEM["0"], P.user_0(dict(
                product_input=D.user_domain(project.context if project else {}, []).split("\n\nСправочник")[0],
                hypotheses=[{"code": h.code, "kind": h.kind, "text": " ".join(_statement(x) for x in h.lines)} for h in hyps],
                components=raw)))
        finally:
            await llm.aclose()
        by_id = {c["component_id"]: c for c in raw}
        hyp_by_code = {h.code: h for h in hyps}
        await s.execute(delete(Component).where(Component.hypothesis_id.in_([h.id for h in hyps])))
        n = 0
        for comp in obj["components"]:
            src = by_id.get(comp.get("component_id"))
            if not src:
                continue
            parts = comp.get("parts") or []
            for p in parts:
                s.add(Component(
                    hypothesis_id=hyp_by_code[src["hypothesis_ids"][0]].id,
                    component_id=p.get("part_id") or src["component_id"], parent_component_id=src["component_id"],
                    slot=src["slot"], statement=p.get("statement") or src["statement"],
                    verification_method=src["verification_method"], quantifier=p.get("quantifier", "occurrence"),
                    auto_split=len(parts) > 1))
                n += 1
        await s.commit()
        return n


# ------------------------------------------------------------------ область проекта
async def ensure_catalog(s: AsyncSession) -> None:
    have = set((await s.scalars(select(Subdomain.code))).all())
    missing = [r for r in CATALOG if r["code"] not in have]
    if not missing:
        return
    vecs = D.embed([D.subdomain_text(r["name"], "") for r in missing])
    for r, v in zip(missing, vecs, strict=True):
        s.add(Subdomain(code=r["code"], industry_code=r["industry_code"], industry_name=r["industry_name"],
                        name=r["name"], description="", embedding=v))
    await s.commit()


async def detect_domain(project_id: str) -> dict[str, Any]:
    async with SessionLocal() as s:
        await ensure_catalog(s)
        if (await s.scalars(select(ProjectDomain).where(ProjectDomain.project_id == project_id))).first():
            return {"status": "already_set"}  # область задаётся один раз и не меняется
        project = await s.get(Project, project_id)
        subs = (await s.scalars(select(Subdomain).where(Subdomain.merged_into.is_(None)))).all()
        catalog = [dict(code=x.code, industry_name=x.industry_name, name=x.name) for x in subs]
        llm = _llm(project_id)
        try:
            obj = await llm.call("domain", D.SYSTEM_DOMAIN, D.user_domain(project.context if project else {}, catalog))
            primary = obj.get("primary_subdomain")
            new = obj.get("new_subdomain")
            if not primary and new:
                vec = D.embed([D.subdomain_text(new["name"], new.get("description", ""))])[0]
                best = max(subs, key=lambda x: D.cosine(vec, x.embedding) if x.embedding is not None else -1)
                same = False
                if best.embedding is not None and D.cosine(vec, best.embedding) >= D.DUP_THRESHOLD:
                    ans = await llm.call("dedup", D.SYSTEM_DEDUP, D.user_dedup(
                        new, dict(code=best.code, name=best.name, description=best.description)))
                    same = bool(ans.get("same"))
                if same:
                    primary = best.code
                else:
                    primary = new["code"]
                    s.add(Subdomain(code=primary, industry_code=new.get("industry_code", "OTHER"),
                                    industry_name=new.get("industry_name", "Другое"), name=new["name"],
                                    description=new.get("description", ""), embedding=vec, added_by="llm",
                                    source_project_id=project_id))
                    await s.flush()
        finally:
            await llm.aclose()
        known = {x.code for x in subs} | {primary}
        s.add(ProjectDomain(project_id=project_id, subdomain_code=primary, is_primary=True,
                            rationale=obj.get("rationale", ""), confidence=obj.get("confidence", "high")))
        for code in (obj.get("secondary_subdomains") or [])[:2]:
            if code in known and code != primary:
                s.add(ProjectDomain(project_id=project_id, subdomain_code=code, is_primary=False))
        await s.commit()
        return {"primary": primary, "secondary": obj.get("secondary_subdomains") or [], "confidence": obj.get("confidence")}


async def executor_for(s: AsyncSession, project_id: str) -> str:
    """Исполнитель LLM-шагов: < 5 проектов в основной подобласти → API, иначе локальная модель."""
    pd = (await s.scalars(select(ProjectDomain).where(ProjectDomain.project_id == project_id, ProjectDomain.is_primary))).first()
    sub = await s.get(Subdomain, pd.subdomain_code) if pd else None
    return "local" if sub and sub.trained_projects >= 5 else "api"


# ------------------------------------------------------------------ шаг 3а: вопрос плана → компоненты
async def _components_view(s: AsyncSession, project_id: str, segment_code: str) -> list[Component]:
    q = (select(Component).join(Hypothesis)
         .where(Hypothesis.project_id == project_id, Hypothesis.segment_code == segment_code, Hypothesis.selected))
    return list((await s.scalars(q)).all())


async def map_plan(project_id: str, segment_code: str) -> int:
    async with SessionLocal() as s:
        comps = await _components_view(s, project_id, segment_code)
        qs = (await s.scalars(select(PlanQuestion).where(PlanQuestion.project_id == project_id,
                                                         PlanQuestion.segment_code == segment_code))).all()
        plan = [dict(question_id=q.question_id, section=q.section, text=q.text) for q in qs]
        llm = _llm(project_id)
        try:
            obj = await llm.call("3a", P.SYSTEM["3a"], P.user_3a(dict(plan=plan), [
                dict(component_id=c.component_id, statement=c.statement, verification_method=c.verification_method)
                for c in comps]))
        finally:
            await llm.aclose()
        links = {x["question_id"]: x.get("component_ids", []) for x in obj["question_components"]}
        for q in qs:
            q.component_ids = links.get(q.question_id, [])
        await s.commit()
        return sum(len(v) for v in links.values())


# ------------------------------------------------------------------ подготовка проекта целиком
async def prepare_project(project_id: str, force: bool = False) -> dict[str, Any]:
    """Шаг 0 → область → шаг 3а по всем сегментам. Один раз на проект (повторно — только force).

    Транзакционная блокировка по проекту: обработка интервью, загруженных параллельно, ждёт одну подготовку,
    а не запускает свою (13.11.2026 интервью обработалось раньше шага 0 и получило 0 пар).
    """
    async with SessionLocal() as s, s.begin():
        await s.execute(text("select pg_advisory_xact_lock(hashtext(:p))"), {"p": "prepare:" + project_id})
        n_comp = await s.scalar(select(func.count()).select_from(Component).join(Hypothesis)
                                .where(Hypothesis.project_id == project_id, Hypothesis.selected))
        linked = await s.scalar(select(func.count()).select_from(PlanQuestion)
                                .where(PlanQuestion.project_id == project_id,
                                       PlanQuestion.component_ids != text("'[]'::jsonb")))
        if n_comp and linked and not force:
            return {"status": "already_prepared", "components": n_comp}
        n = await prepare_components(project_id)
        domain = await detect_domain(project_id)
        segments = sorted(set((await s.scalars(select(Hypothesis.segment_code)
                                                .where(Hypothesis.project_id == project_id))).all()))
        links = {seg: await map_plan(project_id, seg) for seg in segments}
        return {"components": n, "domain": domain, "plan_links": links}


async def set_progress(interview_id: int, fraction: float, restart: bool = False) -> None:
    """Доля пройденного внутри текущего статуса интервью (индикатор экрана 08). Отдельная короткая транзакция:
    основная сессия обработки держит незафиксированные утверждения и пары до конца шага 5."""
    values: dict[str, Any] = {"stage_progress": round(min(max(fraction, 0.0), 1.0), 3)}
    if restart:
        values["stage_started_at"] = func.now()
    async with SessionLocal() as s:
        await s.execute(update(Interview).where(Interview.id == interview_id).values(**values))
        await s.commit()


# ------------------------------------------------------------------ шаг 1: распознавание и диаризация
async def transcribe(interview_id: int) -> int:
    async with SessionLocal() as s:
        iv = await s.get(Interview, interview_id)
        if iv is None:
            return 0
        iv.status, iv.error = "transcribing", None
        await s.commit()
        await set_progress(interview_id, 0, restart=True)
        try:
            result = None
            if iv.nexara_job_id:  # повтор: задача в Nexara уже создана и оплачена — дожидаемся её, а не шлём файл снова
                try:
                    result = await wait_job(iv.nexara_job_id)
                except NexaraError:
                    result = None
            if result is None:
                storage = make_client(get_settings())
                obj = storage.get_object(get_settings().minio_bucket, iv.object_key)
                try:
                    data = obj.read()
                finally:
                    obj.close()
                    obj.release_conn()
                iv.nexara_job_id = await create_job(iv.filename, data)
                await s.commit()
                result = await wait_job(iv.nexara_job_id)
            turns = segments_to_turns(result)
            await s.execute(delete(Turn).where(Turn.interview_id == iv.id))
            for t in turns:
                s.add(Turn(interview_id=iv.id, **t))
            iv.asr_raw, iv.duration_sec, iv.status = result, result.get("duration"), "transcribed"
            iv.claims_ready, iv.step5_done = False, []  # новые реплики — прежние утверждения и пары неактуальны
            await s.commit()
            return len(turns)
        except Exception as e:
            await s.rollback()
            iv = await s.get(Interview, interview_id)
            if iv:
                iv.status, iv.error = "error", f"Расшифровка: {e}"[:1000]
                await s.commit()
            raise


# ------------------------------------------------------------------ шаг 5: пакет утверждений × компоненты
async def pairs_batch(llm: Llm, comps: list[dict[str, Any]], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Шаг 5 с облегчённым рассуждением (reasoning_effort=low, решение владельца 15.11.2026 вместо полного от
    12.11.2026: полное в 68 % времени упиралось в лимит 32 000 токенов без ответа; на эталоне разница low / полное
    в пределах разброса повторных прогонов — TEST_PLAN.md п. 1). Если ответ не получен — пакет делится пополам,
    одиночное утверждение в крайнем случае размечается без рассуждения."""
    try:
        return list((await llm.call("5", P.SYSTEM["5"], P.user_5(comps, claims), thinking=True, retries=0,
                                    extra=LOW_REASONING))["pairs"])
    except LlmError:
        if len(claims) > 1:
            mid = len(claims) // 2
            return await pairs_batch(llm, comps, claims[:mid]) + await pairs_batch(llm, comps, claims[mid:])
    return list((await llm.call("5", P.SYSTEM["5"], P.user_5(comps, claims)))["pairs"])


# ------------------------------------------------------------------ шаги 2–6 по одному интервью
async def process_interview(interview_id: int) -> dict[str, int]:
    async with SessionLocal() as s:
        iv = await s.get(Interview, interview_id)
        if iv is None:
            return {}
        project = await s.get(Project, iv.project_id)
        iv.status, iv.error = "processing", None
        await s.commit()
        await set_progress(interview_id, 0, restart=True)
        llm = _llm(iv.project_id, iv.id)
        try:
            await prepare_project(iv.project_id)  # без компонентов и связей плана пары не строятся
            await set_progress(interview_id, PROGRESS["prepared"])
            turns = (await s.scalars(select(Turn).where(Turn.interview_id == iv.id).order_by(Turn.turn_index))).all()
            qs = (await s.scalars(select(PlanQuestion).where(PlanQuestion.project_id == iv.project_id,
                                                             PlanQuestion.segment_code == iv.segment_code))).all()
            if iv.claims_ready:
                # контрольная точка: шаги 2–4 уже сделаны и сохранены — продолжаем с шага 5
                claims = list((await s.scalars(select(Claim).where(Claim.interview_id == iv.id)
                                               .order_by(Claim.id))).all())
            else:
                claims = await extract_claims(s, iv, project, turns, qs, llm)
            await set_progress(interview_id, PROGRESS["claims"])
            n_pairs = await match_pairs(iv, claims, qs, llm)
            iv.status = "processed"
            await s.commit()
            return {"turns": len(turns), "claims": len(claims), "pairs": n_pairs,
                    "quotes_not_found": sum(not c.quote_ok for c in claims)}
        except Exception as e:
            await s.rollback()
            iv = await s.get(Interview, interview_id)
            if iv:
                iv.status, iv.error = "error", f"Обработка: {e}"[:1000]
                await s.commit()
            raise
        finally:
            await llm.aclose()


async def extract_claims(s: AsyncSession, iv: Interview, project: Project | None, turns: Sequence[Turn],
                         qs: Sequence[PlanQuestion], llm: Llm) -> list[Claim]:
    """Шаги 2–4 (+6). Утверждения сохраняются сразу (контрольная точка claims_ready): сбой на шаге 5 их не теряет."""
    interview_id = iv.id
    for t in turns:  # шаг 2: только имена → [ИМЯ]
        t.text_anon = anonymize_names(t.text)
    await s.commit()
    view = [dict(turn_index=t.turn_index, speaker_role=t.speaker_role, text=t.text_anon or t.text) for t in turns]
    proj = dict(name=project.name if project else "", plan=[dict(question_id=q.question_id, text=q.text) for q in qs])

    # шаг 3б: реплики интервьюера → вопросы плана
    marks = {m["turn_index"]: m for m in await llm.chunked("3b", proj, view)}
    for t in turns:
        m = marks.get(t.turn_index)
        if m and t.speaker_role == "interviewer":
            t.has_question, t.question_ids = bool(m.get("has_question")), list(m.get("question_ids") or [])
            t.off_plan, t.leading_question = bool(m.get("off_plan")), bool(m.get("leading_question"))
    await s.commit()
    await set_progress(interview_id, PROGRESS["matched"])

    # шаг 4: атомарные утверждения (+ шаг 6: цитата дословно в реплике)
    raw_claims = await llm.chunked("4", proj, view)
    await s.execute(delete(Claim).where(Claim.interview_id == iv.id))
    text_of = {t.turn_index: (t.text_anon or t.text) for t in turns}
    q_turns = sorted(t.turn_index for t in turns if t.has_question)
    counter: dict[int, int] = defaultdict(int)
    claims: list[Claim] = []
    for c in raw_claims:
        ti = int(c["turn_index"])
        counter[ti] += 1
        prev_q = max((i for i in q_turns if i < ti), default=None)
        qids = next((t.question_ids for t in turns if t.turn_index == prev_q), []) if prev_q is not None else []
        claim = Claim(interview_id=iv.id, claim_id=f"{iv.respondent_code}_T{ti:03d}_A{counter[ti]:02d}",
                      turn_index=ti, claim_text=c["claim_text"], source_quote=c["source_quote"],
                      quote_ok=c["source_quote"] in text_of.get(ti, ""), subject=c["subject"], kind=c["kind"],
                      period=c["period"], question_ids=qids)
        s.add(claim)
        claims.append(claim)
    iv.claims_ready, iv.step5_done = True, []
    await s.commit()  # контрольная точка: утверждения сохранены
    return claims


async def match_pairs(iv: Interview, claims: Sequence[Claim], qs: Sequence[PlanQuestion], llm: Llm) -> int:
    """Шаг 5: пары утверждение × компонент (облегчённое рассуждение, пакеты по BATCH5, до STEP5_CONCURRENCY сразу).
    Каждый пакет сохраняется сам — пары и отметка в step5_done одной транзакцией; при повторе готовые пакеты
    пропускаются. Пакеты параллельно (TEST_PLAN.md п. 1.1): запросы те же, что и по очереди, метки не меняются."""
    interview_id = iv.id
    async with SessionLocal() as s:
        comps = await _components_view(s, iv.project_id, iv.segment_code)
        done = set((await s.scalar(select(Interview.step5_done).where(Interview.id == interview_id))) or [])
    comp_pk = {c.component_id: c.id for c in comps}
    pv = [dict(component_id=c.component_id, statement=c.statement, verification_method=c.verification_method,
               quantifier=c.quantifier) for c in comps]
    question_text = {q.question_id: q.text for q in qs}
    cv = [dict(claim_id=c.claim_id, claim_text=c.claim_text, source_quote=c.source_quote,
               question="; ".join(question_text.get(x, x) for x in c.question_ids)) for c in claims]
    claim_pk = {c.claim_id: c.id for c in claims}
    batches = list(range(0, len(cv), BATCH5))
    sem = asyncio.Semaphore(STEP5_CONCURRENCY)
    finished = len([b for b in batches if b // BATCH5 in done])

    async def run_batch(b: int) -> int:
        nonlocal finished
        async with sem:
            res = await pairs_batch(llm, pv, cv[b:b + BATCH5])
        rows = [Pair(claim_pk=claim_pk[str(p["claim_id"])], component_pk=comp_pk[str(p["component_id"])],
                     label=p["label"], rationale=p.get("rationale", ""))
                for p in res if str(p.get("claim_id")) in claim_pk and str(p.get("component_id")) in comp_pk
                and p.get("label") in ("S", "C", "RI")]
        uniq = {(r.claim_pk, r.component_pk): r for r in rows}  # модель изредка повторяет пару
        async with SessionLocal() as ws:
            pks = [claim_pk[c["claim_id"]] for c in cv[b:b + BATCH5]]
            await ws.execute(delete(Pair).where(Pair.claim_pk.in_(pks)))  # на случай частичных данных
            ws.add_all(uniq.values())
            await ws.execute(update(Interview).where(Interview.id == interview_id).values(
                step5_done=Interview.step5_done.op("||")(func.to_jsonb(b // BATCH5))))
            await ws.commit()
        finished += 1
        await set_progress(interview_id, PROGRESS["claims"] + (1 - PROGRESS["claims"]) * finished / max(len(batches), 1))
        return len(uniq)

    todo = [b for b in batches if b // BATCH5 not in done]
    results = await asyncio.gather(*(run_batch(b) for b in todo), return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    if errors:  # готовые пакеты уже сохранены; «Повторить» доделает остальные
        raise errors[0]
    async with SessionLocal() as s:
        n: int = await s.scalar(select(func.count()).select_from(Pair).join(Claim, Pair.claim_pk == Claim.id)
                                .where(Claim.interview_id == interview_id)) or 0
    return n


# ------------------------------------------------------------------ ИГ2: статусы компонентов и гипотез
async def results(project_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as s:
        hyps = (await s.scalars(select(Hypothesis).where(Hypothesis.project_id == project_id, Hypothesis.selected))).all()
        out = []
        for h in hyps:
            ivs = (await s.scalars(select(Interview).where(Interview.project_id == project_id,
                                                           Interview.segment_code == h.segment_code,
                                                           Interview.status == "processed"))).all()
            respondents = [i.respondent_code for i in ivs]
            comps = (await s.scalars(select(Component).where(Component.hypothesis_id == h.id))).all()
            rows = []
            for comp in comps:
                q = (select(Pair, Claim, Interview).join(Claim, Pair.claim_pk == Claim.id)
                     .join(Interview, Claim.interview_id == Interview.id).where(Pair.component_pk == comp.id))
                by_resp: dict[str, list[ig2.Evidence]] = defaultdict(list)
                for pair, claim, iv in (await s.execute(q)).all():
                    by_resp[iv.respondent_code].append(ig2.Evidence(
                        respondent=iv.respondent_code, label=pair.label, subject=claim.subject,
                        turn_index=claim.turn_index, claim_id=claim.claim_id, quote=claim.source_quote))
                r = ig2.component_status(by_resp, respondents, comp.quantifier)
                quotes = [dict(respondent=e.respondent, label=e.label, quote=e.quote)
                          for ev in by_resp.values() for e in ev if e.label in ("S", "C")][:6]
                rows.append(dict(component_id=comp.component_id, slot=comp.slot, statement=comp.statement,
                                 quantifier=comp.quantifier, verification_method=comp.verification_method,
                                 status=r.status, k=r.k, c=r.c, m=r.m, ri_only=r.ri_only, mixed=r.mixed,
                                 third_party_only=r.third_party_only, quotes=quotes))
            status, percent = ig2.hypothesis_percent([str(x["status"]) for x in rows], len(respondents))
            out.append(dict(hypothesis=h.code, kind=h.kind, segment=h.segment_code, status=status, percent=percent,
                            interviews=len(respondents), components=rows))
        return out
