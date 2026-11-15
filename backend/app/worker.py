"""Воркер фоновых задач (arq + Redis): модуль коллеги, подготовка анализа, транскрибация и ИГ1, стенограмма, ИГ3.

Задачи уровня проекта отмечают состояние в project_jobs (running → done | error) — по нему интерфейс показывает
«идёт обработка» и «не удалось» (экраны 03.1, 04.1, 05.1, 09.1, 10.1, 11.2).
"""
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings

from app.core.config import get_settings

HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL_SECONDS = 90


async def heartbeat(ctx: dict[str, Any]) -> None:
    await ctx["redis"].set(HEARTBEAT_KEY, "1", ex=HEARTBEAT_TTL_SECONDS)


async def ping(ctx: dict[str, Any], value: str) -> str:
    """Тестовая задача: проверяет путь API → очередь → воркер."""
    return f"pong:{value}"


async def set_job(project_id: str, kind: str, status: str, error: str | None = None) -> None:
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models import ProjectJob

    async with SessionLocal() as s:
        row = (await s.scalars(select(ProjectJob).where(ProjectJob.project_id == project_id,
                                                        ProjectJob.kind == kind))).first()
        if row is None:
            s.add(ProjectJob(project_id=project_id, kind=kind, status=status, error=error))
        else:
            row.status, row.error = status, error
        await s.commit()


async def tracked(project_id: str, kind: str, fn: Callable[[], Awaitable[Any]]) -> Any:
    await set_job(project_id, kind, "running")
    try:
        result = await fn()
    except Exception as e:
        await set_job(project_id, kind, "error", f"{e}"[:1000])
        raise
    await set_job(project_id, kind, "done")
    return result


async def design_hypotheses(ctx: dict[str, Any], project_id: str) -> Any:
    from app.design import service

    return await tracked(project_id, "hypotheses", lambda: service.run_hypotheses(project_id))


async def design_scenario(ctx: dict[str, Any], project_id: str) -> Any:
    from app.design import service

    return await tracked(project_id, "scenario", lambda: service.run_scenario(project_id))


async def prepare_project(ctx: dict[str, Any], project_id: str) -> Any:
    """Шаг 0 (компоненты) → область проекта → шаг 3а по каждому сегменту."""
    from app.ig1 import pipeline

    return await tracked(project_id, "prepare", lambda: pipeline.prepare_project(project_id, force=True))


INTERVIEW_LOCK_SECONDS = 4 * 60 * 60  # дольше job_timeout: замок не снимется раньше конца самой долгой обработки


async def interview_locked(ctx: dict[str, Any], interview_id: int, fn: Callable[[], Awaitable[Any]]) -> Any:
    """Одна обработка записи за раз. 15.11.2026 две задачи одной записи шли параллельно (повторное «Повторить»
    до введения единого id задачи): обе удаляли и писали утверждения, деньги тратились дважды."""
    key = f"lock:interview:{interview_id}"
    if not await ctx["redis"].set(key, "1", nx=True, ex=INTERVIEW_LOCK_SECONDS):
        return {"skipped": "запись уже обрабатывается другой задачей"}
    try:
        return await fn()
    finally:
        await ctx["redis"].delete(key)


async def transcribe_and_process(ctx: dict[str, Any], interview_id: int) -> dict[str, Any]:
    from app.ig1 import pipeline

    async def run() -> dict[str, Any]:
        turns = await pipeline.transcribe(interview_id)
        return {"turns": turns, **await pipeline.process_interview(interview_id)}
    result: dict[str, Any] = await interview_locked(ctx, interview_id, run)
    return result


async def process_interview_job(ctx: dict[str, Any], interview_id: int) -> dict[str, Any]:
    from app.ig1 import pipeline

    result: dict[str, Any] = await interview_locked(ctx, interview_id, lambda: pipeline.process_interview(interview_id))
    return result


async def stenogram_job(ctx: dict[str, Any], project_id: str) -> Any:
    from app.ig1 import stenogram

    return await tracked(project_id, "stenogram", lambda: stenogram.run_project(project_id))


async def insights_job(ctx: dict[str, Any], project_id: str) -> Any:
    from app.ig3 import pipeline

    return await tracked(project_id, "insights", lambda: pipeline.run_project(project_id))


async def reformulate_job(ctx: dict[str, Any], project_id: str) -> Any:
    """«Переформулировать гипотезы» (11.2): модуль коллеги с interview_summary по итогам ИГ2 и ИГ3."""
    from app.design import service
    from app.reports import interview_summary

    async def run() -> Any:
        return await service.run_hypotheses(project_id, summary=await interview_summary(project_id))
    return await tracked(project_id, "reformulate", run)


async def startup(ctx: dict[str, Any]) -> None:
    await heartbeat(ctx)


class WorkerSettings:
    # Задачи интервью ставятся с постоянным id (interview:<id>); результат не храним (keep_result=0), иначе arq
    # ещё час после завершения отклонял бы «Повторить» для той же записи.
    functions: ClassVar[list[Any]] = [ping, design_hypotheses, design_scenario, prepare_project,
                                      func(transcribe_and_process, keep_result=0),
                                      func(process_interview_job, keep_result=0),
                                      stenogram_job, insights_job, reformulate_job]
    job_timeout = 3 * 60 * 60  # расшифровка длинной записи в Nexara может идти долго
    max_jobs = 4
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, second={0, 30})]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
