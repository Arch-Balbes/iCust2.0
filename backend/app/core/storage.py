"""Объектное хранилище MinIO (S3): записи интервью, документы, выгрузки."""
import asyncio

from minio import Minio

from app.core.config import Settings


def make_client(settings: Settings) -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
    )


async def ensure_bucket(client: Minio, bucket: str) -> None:
    """Создаёт бакет, если его нет. Клиент minio синхронный — выносим в поток."""
    if not await asyncio.to_thread(client.bucket_exists, bucket):
        await asyncio.to_thread(client.make_bucket, bucket)


async def bucket_ok(client: Minio, bucket: str) -> bool:
    return bool(await asyncio.to_thread(client.bucket_exists, bucket))
