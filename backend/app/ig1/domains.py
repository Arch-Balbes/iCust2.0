"""Определение области и подобласти проекта (PROJECT_DOMAINS.md, решение 12.11.2026).

LLM по анкете А–Ж выбирает одну основную подобласть и до двух дополнительных из справочника; если ни одна
не подходит — предлагает новую. Новая проверяется на дубликат локальными эмбеддингами (fastembed, решение
13.11.2026): при косинусной близости ≥ DUP_THRESHOLD LLM решает, одно ли это; иначе подобласть добавляется
с пометкой added_by=llm. Область задаётся при создании проекта и дальше не меняется.
"""
import json
from functools import lru_cache
from typing import Any

import numpy as np

from app.core.config import get_settings

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DUP_THRESHOLD = 0.85  # стартовое значение, калибруется на первых случаях

SYSTEM_DOMAIN = """Ты классифицируешь проект продуктового исследования по области. Область — сфера, в которой живёт проблема респондентов (их работа, быт, покупки), а не технология продукта (ИИ, бот, приложение) и не бизнес-модель. Пример: ИИ-стилист в Telegram — «гардероб и стиль», а не «ИИ».

По анкете проекта выбери из справочника:
- primary_subdomain — одну основную подобласть по проблеме основного сегмента;
- secondary_subdomains — до двух дополнительных (другие сегменты и сценарии), можно пусто;
- rationale — одно-два предложения почему;
- confidence — "high" или "low".
Если ни одна подобласть справочника не подходит по смыслу, primary_subdomain = null и заполни new_subdomain: {"code": "snake_case", "name": "...", "description": "кто и с какой проблемой", "industry_code": "код существующей отрасли или новый КАПСОМ", "industry_name": "..."}. Иначе new_subdomain = null.

Форма ответа:
{"primary_subdomain": "code|null", "secondary_subdomains": ["code"], "rationale": "...", "confidence": "high|low", "new_subdomain": null}
Ответь ТОЛЬКО одним JSON-объектом указанной формы, без пояснений и без markdown-обёртки. Пиши по-русски."""

SYSTEM_DEDUP = """Тебе дают две подобласти справочника областей продуктовых исследований. Ответь, одна ли это подобласть по смыслу (одни и те же люди с той же проблемой и общей лексикой), или разные.
Форма ответа: {"same": true|false, "reason": "кратко"}
Ответь ТОЛЬКО одним JSON-объектом, без markdown. Пиши по-русски."""

CONTEXT_LABELS = {
    "product": "А. Продукт", "role": "Б. Для кого (роль)", "job": "Б1. Задача", "situation": "Б2. Ситуация",
    "problem": "В. Проблема", "losses": "В1. Потери", "function": "Г. Функция", "outcome": "Д. Результат",
    "effect": "Д1. Эффект", "alternatives": "Е. Текущие способы", "decision": "Ж. Решение по итогам",
}


@lru_cache(maxsize=1)
def _embedder():  # type: ignore[no-untyped-def]
    from fastembed import TextEmbedding

    return TextEmbedding(EMBED_MODEL, cache_dir=get_settings().models_cache_dir)


def embed(texts: list[str]) -> list[list[float]]:
    vecs = list(_embedder().embed(texts))
    return [(v / (np.linalg.norm(v) or 1.0)).astype(float).tolist() for v in vecs]


def cosine(a: list[float], b: list[float]) -> float:
    return float(np.dot(np.asarray(a), np.asarray(b)))


def subdomain_text(name: str, description: str) -> str:
    return f"{name}. {description}".strip(". ")


def user_domain(context: dict[str, Any], catalog: list[dict[str, Any]]) -> str:
    anketa = "\n".join(f"{label}: {context.get(k, '')}" for k, label in CONTEXT_LABELS.items() if context.get(k))
    cat = "\n".join(f"{r['code']} — {r['industry_name']} / {r['name']}" for r in catalog)
    return f"Анкета проекта:\n{anketa}\n\nСправочник подобластей (код — отрасль / подобласть):\n{cat}"


def user_dedup(a: dict[str, Any], b: dict[str, Any]) -> str:
    return json.dumps({"новая": a, "существующая": b}, ensure_ascii=False)
