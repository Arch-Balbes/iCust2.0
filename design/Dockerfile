# Модуль генерации дизайна исследования (коллега, icust_module v1.0) — отдельный сервис.
# Python 3.12 и свои зависимости (torch, sentence-transformers), поэтому не внутри нашего бэкенда.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/hf ICUST_DEVICE=cpu \
    ICUST_RAW_DIR=/data/raw/2026-11-09 ICUST_PROCESSED_DIR=/data/processed/2026-11-09

WORKDIR /srv
COPY icust_module/requirements.txt ./
# torch — сборка для CPU (без CUDA образ меньше в разы); версия та же, что в requirements модуля
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --progress-bar off "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu \
    && pip install --progress-bar off -r requirements.txt

COPY icust_module/ ./icust_module/
COPY entrypoint.sh ./
RUN useradd --create-home --uid 1000 icust && mkdir -p /models /data/processed && chown -R icust /models /data/processed
USER icust
WORKDIR /srv/icust_module/src
EXPOSE 8000
CMD ["sh", "/srv/entrypoint.sh"]
