"""Вызов LLM (Cloud.ru Foundation Models, OpenAI-совместимый API) и учёт расхода токенов."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from . import config

log = logging.getLogger(__name__)

PROVIDERS = {"cloudru": {"base_url": "https://foundation-models.api.cloud.ru/v1", "key_env": config.API_KEY_ENV}}
_THINK_OFF = {"extra_body": {"chat_template_kwargs": {"enable_thinking": False, "thinking": False}}}
MODEL_REGISTRY = {
    "cloudru:deepseek-ai/DeepSeek-V4-Pro": {"family": "deepseek", "hosting": "ru", "reasoning_off": _THINK_OFF},
    "cloudru:zai-org/GLM-5.1":             {"family": "glm",      "hosting": "ru", "reasoning_off": _THINK_OFF},
}
RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)

_CLIENTS: dict = {}
_CLIENTS_LOCK = threading.Lock()
_CACHE = None


def split_model(spec: str) -> tuple[str, str]:
    """'cloudru:zai-org/GLM-5.1' -> ('cloudru', 'zai-org/GLM-5.1')."""
    prefix, _, rest = spec.partition(":")
    if prefix not in PROVIDERS or not rest:
        raise ValueError(f"Неизвестный провайдер в {spec!r}: модуль работает только с Cloud.ru")
    return prefix, rest


def get_client(provider: str) -> OpenAI:
    with _CLIENTS_LOCK:
        if provider not in _CLIENTS:
            p = PROVIDERS[provider]
            key = os.getenv(p["key_env"])
            if not key:
                raise RuntimeError(f"Не задан ключ {p['key_env']} (переменная окружения или .env)")
            _CLIENTS[provider] = OpenAI(base_url=p["base_url"], api_key=key, timeout=config.LLM_TIMEOUT_S,
                                        max_retries=0)
        return _CLIENTS[provider]


def model_params(spec: str) -> dict:
    if spec not in MODEL_REGISTRY:
        raise KeyError(f"Модели {spec!r} нет в MODEL_REGISTRY")
    return MODEL_REGISTRY[spec]["reasoning_off"]


def _cache():
    """Дисковый кэш ответов — только если задан ICUST_LLM_CACHE_DIR (для отладки; в проде выключен)."""
    global _CACHE
    if _CACHE is None and config.LLM_CACHE_DIR is not None:
        import diskcache
        _CACHE = diskcache.Cache(str(config.LLM_CACHE_DIR))
    return _CACHE


def llm_call(model: str, messages: list[dict], schema: dict | None = None, temperature: float = 0.7,
             sample_idx: int = 0, validate=None, max_retries: int | None = None) -> dict:
    """Вызов LLM: повторы при 429 / 5xx / тайм-ауте, структурированный ответ по JSON-схеме, валидация.

    Возвращает dict: content, data (разобранный JSON), valid, cached, error, call (модель, токены, задержка).
    """
    max_retries = config.LLM_MAX_RETRIES if max_retries is None else max_retries
    extra = model_params(model)
    provider, model_name = split_model(model)
    call = {"model_spec": model, "cached": False, "status": None, "problems": None,
            "prompt_tokens": 0, "completion_tokens": 0, "latency_s": None}

    cache = _cache()
    key = None
    if cache is not None:
        payload = {"model": model, "messages": messages, "schema": schema,
                   "temperature": temperature, "sample_idx": sample_idx, **extra}
        key = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if key in cache:
            hit = cache[key]
            if validate is None or validate(hit["data"]):
                u = hit.get("usage") or {}
                call.update(cached=True, status="ok", prompt_tokens=u.get("prompt") or 0,
                            completion_tokens=u.get("completion") or 0, latency_s=hit.get("latency_s"))
                return {"content": hit["content"], "data": hit["data"], "valid": True, "cached": True,
                        "error": None, "call": call}
            del cache[key]

    params = {"model": model_name, "messages": messages, "temperature": temperature, **extra}
    if schema:
        params["response_format"] = {"type": "json_schema", "json_schema": schema}

    r, err = None, None
    for attempt in range(max_retries):
        t = time.time()
        try:
            r = get_client(provider).chat.completions.create(**params)
            call["latency_s"] = round(time.time() - t, 2)
            break
        except RETRYABLE as e:
            err = e
        except APIStatusError as e:
            if e.status_code < 500:
                raise
            err = e
        wait = 2 ** attempt * 5
        log.warning("%s: %s, попытка %d/%d, ждём %d с", model, type(err).__name__, attempt + 1, max_retries, wait)
        time.sleep(wait)

    if r is None:
        call.update(status="error", problems=f"{type(err).__name__}: {str(err)[:200]}")
        return {"content": None, "data": None, "valid": False, "cached": False, "error": call["problems"], "call": call}

    content = r.choices[0].message.content
    try:
        data = json.loads(content) if schema else None
    except (json.JSONDecodeError, TypeError):
        data = None
    valid = data is not None if schema else content is not None
    if valid and validate is not None:
        valid = bool(validate(data))
    usage = r.usage
    call.update(status="ok" if valid else "invalid",
                prompt_tokens=(usage.prompt_tokens or 0) if usage else 0,
                completion_tokens=(usage.completion_tokens or 0) if usage else 0)
    if cache is not None and valid:
        cache[key] = {"content": content, "data": data, "model": r.model, "call_id": f"call_{uuid.uuid4().hex[:12]}",
                      "latency_s": call["latency_s"],
                      "usage": {"prompt": call["prompt_tokens"], "completion": call["completion_tokens"], "reasoning": 0}}
    return {"content": content, "data": data, "valid": valid, "cached": False, "error": None, "call": call}


class Meta:
    """Расход токенов и предупреждения этапа -> поле meta ответа."""

    def __init__(self):
        self.prompt_tokens = self.completion_tokens = self.llm_calls = self.cached_calls = 0
        self.models: set[str] = set()
        self.warnings: list[str] = []

    def add(self, call: dict) -> None:
        self.llm_calls += 1
        self.cached_calls += int(call["cached"])
        self.prompt_tokens += call["prompt_tokens"] or 0
        self.completion_tokens += call["completion_tokens"] or 0
        self.models.add(call["model_spec"])

    def warn(self, text: str) -> None:
        self.warnings.append(text)

    def merge(self, other: "Meta") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.llm_calls += other.llm_calls
        self.cached_calls += other.cached_calls
        self.models |= other.models
        self.warnings += other.warnings

    def to_dict(self) -> dict:
        return {"usage": {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                          "total_tokens": self.prompt_tokens + self.completion_tokens},
                "llm_calls": self.llm_calls, "cached_calls": self.cached_calls,
                "models": sorted(self.models), "warnings": self.warnings}
