FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала зависимости — слой кэшируется, пока не меняется pyproject.toml
COPY pyproject.toml ./
# Кэш pip между сборками (BuildKit): при смене зависимостей скачиваются только новые пакеты
RUN --mount=type=cache,target=/root/.cache/pip \
    mkdir app && touch app/__init__.py \
    && PIP_NO_CACHE_DIR=0 pip install --progress-bar off -e ".[dev]" \
    && rm -rf app

COPY . .

# /models — кэш локальных моделей (эмбеддинги fastembed); в compose подключается томом models_cache
RUN useradd --create-home --uid 1000 icust && mkdir -p /models && chown -R icust /app /models
USER icust

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
