"""Проверка состояния: API и все зависимости (БД, pgvector, Redis, MinIO, воркер)."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.storage import bucket_ok
from app.worker import HEARTBEAT_KEY

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    request: Request, response: Response, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    checks: dict[str, Any] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
        ext = await db.scalar(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        checks["pgvector"] = ext or "missing"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"

    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
        checks["worker"] = "ok" if await request.app.state.redis.exists(HEARTBEAT_KEY) else "no heartbeat"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"

    try:
        ok = await bucket_ok(request.app.state.storage, get_settings().minio_bucket)
        checks["minio"] = "ok" if ok else "bucket missing"
    except Exception as exc:
        checks["minio"] = f"error: {type(exc).__name__}"

    # pgvector отдаёт номер версии, остальные проверки — "ok"
    healthy = all(v == "ok" or (k == "pgvector" and v != "missing") for k, v in checks.items())
    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
