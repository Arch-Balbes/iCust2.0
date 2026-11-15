"""Настройки приложения из переменных окружения (.env в корне репозитория)."""
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "icust"
    postgres_user: str = "icust"
    postgres_password: SecretStr

    redis_url: str = "redis://redis:6379/0"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "icust"
    minio_secret_key: SecretStr
    minio_bucket: str = "icust"
    minio_secure: bool = False

    # Внешние провайдеры (подключаются на следующих этапах)
    # LLM — Cloud.ru Foundation Models, GLM-5.1 (решение 12.11.2026, IG1_PIPELINE.md)
    cloudru_api_key: SecretStr | None = None
    cloudru_base_url: str = "https://foundation-models.api.cloud.ru/v1"
    llm_model: str = "zai-org/GLM-5.1"
    # ASR + диаризация — Nexara
    nexara_api_key: SecretStr | None = None
    nexara_base_url: str = "https://api.nexara.ru/v1"
    # Модуль коллеги (сегменты, гипотезы, сценарий, офферы, дизайн) — сервис design в compose
    design_url: str = "http://design:8000"
    # Локальные модели (NER Natasha, эмбеддинги fastembed) кэшируются в томе
    models_cache_dir: str = "/models"

    @property
    def database_url(self) -> str:
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # обязательные поля (пароли) приходят из окружения
