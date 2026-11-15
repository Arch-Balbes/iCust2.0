"""FastAPI-приложение iCust MVP."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis.asyncio import Redis

from app.api import projects
from app.api.analysis import router as analysis_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.storage import ensure_bucket, make_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.storage = make_client(settings)
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await ensure_bucket(app.state.storage, settings.minio_bucket)
    yield
    await app.state.redis.aclose()


app = FastAPI(
    title="iCust MVP",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(health_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(projects.iv_router, prefix="/api")
