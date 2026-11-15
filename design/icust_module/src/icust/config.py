"""Настройки модуля.

Параметры пайплайна зафиксированы по итогам экспериментов и в запросе не передаются.
Из окружения берутся только ключ, пути к данным и технические параметры (устройство, тайм-аут, кэш).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()   # .env из текущей папки, если есть; переменные окружения имеют приоритет


def _env_path(name: str) -> Path | None:
    v = os.getenv(name)
    return Path(v).expanduser() if v else None


# ---------------------------------------------------------------- окружение
API_KEY_ENV = "CLOUDRU_API_KEY"                         # ключ Cloud.ru Foundation Models — только из окружения
RAW_DIR = _env_path("ICUST_RAW_DIR")                    # data/raw/<снапшот>: реестр, шаблоны, папки кейсов
PROCESSED_DIR = _env_path("ICUST_PROCESSED_DIR")        # data/processed/<снапшот>: parquet после prepare_knowledge_base
DEVICE = os.getenv("ICUST_DEVICE", "auto")              # устройство для моделей retrieval: auto -> cuda / mps / cpu
LLM_TIMEOUT_S = float(os.getenv("ICUST_LLM_TIMEOUT", "180"))      # тайм-аут одного запроса к LLM, с
LLM_MAX_RETRIES = int(os.getenv("ICUST_LLM_MAX_RETRIES", "3"))     # повторов при 429 / 5xx / тайм-ауте
LLM_CACHE_DIR = _env_path("ICUST_LLM_CACHE_DIR")        # кэш ответов LLM на диске; не задан — кэша нет (прод)

# ---------------------------------------------------------------- модели (только Cloud.ru, хостинг в РФ)
GEN_MODEL = "cloudru:deepseek-ai/DeepSeek-V4-Pro"       # генератор: без рассуждений, t = 0.7
JUDGE_MODEL = "cloudru:zai-org/GLM-5.1"                 # оценщик: без рассуждений, t = 0.0
GEN_TEMPERATURE = 0.7
JUDGE_TEMPERATURE = 0.0
EXTRACT_TEMPERATURES = [0.0, 0.7, 0.7]                  # попытки разбиения на элементы формулы

# ---------------------------------------------------------------- цикл генерации
MAX_GENERATIONS = 3       # полных генераций в цикле «генерация -> оценщик»
MAX_ATTEMPTS = 3          # попыток на невалидный ответ
N_SEGMENTS = 3            # сегментов на запрос (пока только 3)
N_HYP_PER_SEGMENT = 2     # гипотез ценности на сегмент (пока только 2)

# ---------------------------------------------------------------- retrieval и фильтры
EMB_MODEL_NAME = "BAAI/bge-m3"
RERANK_MODEL_NAME = "BAAI/bge-reranker-v2-m3"
RERANK_TOP_N = 6
MMR_LAMBDA = 0.5
K_EXAMPLES = 4
LEAK_THRESHOLD = 0.95     # текстовая близость анкеты к кейсу базы, при которой кейс исключается
DEDUPE_THRESHOLD = 0.95   # смысловая близость для фильтра дублей (dedupe=True)

# ---------------------------------------------------------------- фиксированные примеры (основной, резервный)
# Резервный берётся, если анкета запроса совпала с кейсом основного примера (фильтр утечки).
JUDGE_EXAMPLE_SEG = {"main": "C0001", "backup": "C0004"}
JUDGE_EXAMPLE_HYP = {"main": "C0008", "backup": "C0010"}
SCENARIO_EXAMPLE = {"main": "C0008", "backup": "C0006"}
OFFER_EXAMPLE = {"main": "C0010", "backup": "C0009"}
DESIGN_EXAMPLE = {"main": "C0008", "backup": "C0010"}


def pick_example(example: dict, leak_case: str | None) -> str:
    """Основной пример или резервный, если анкета совпала с кейсом основного."""
    return example["backup"] if leak_case == example["main"] else example["main"]
