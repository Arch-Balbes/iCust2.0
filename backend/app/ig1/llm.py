"""Клиент LLM для шагов ИГ1: Cloud.ru Foundation Models (OpenAI-совместимый), GLM-5.1 (решение 12.11.2026).

Шаги 0–4 — без рассуждения (enable_thinking=false), шаг 5 — с облегчённым рассуждением (reasoning_effort=low,
решение 15.11.2026; до него — полное). Шаги 3б и 4 — по кускам интервью
(~24 реплики от вопроса интервьюера, контекст — первые 10 и 8 предыдущих; при обрыве кусок делится пополам).
Логика и параметры перенесены из iCust/scripts/ig1_model_compare/run_step.py.
"""
import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.config import get_settings
from app.ig1 import prompts as P

NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}
CHUNK_TURNS, HEAD_TURNS, OVERLAP_TURNS, MIN_SPLIT = 24, 10, 8, 6
BATCH5 = 15
NET_RETRY_PAUSES = (5, 10, 20, 40, 60, 60, 60)  # секунд между повторами при сбое сети / 429 / 5xx

ENUMS = {
    "quantifier": {"occurrence", "typical"},
    "subject": {"personal", "third_party", "unknown"},
    "kind": {"fact", "routine", "desire_or_hypothetical"},
    "period": {"past", "current", "recurrent", "unspecified"},
    "label": {"S", "C", "RI"},
}
RESULT_KEY = {"0": "components", "3a": "question_components", "3b": "turns", "4": "claims", "5": "pairs",
              "domain": "primary_subdomain", "dedup": "same",
              # стенограмма (экран 09) и ИГ3 (map → reduce → merge → check)
              "sten": "answers", "sten_sum": "summaries",
              "ig3_map": "observations", "ig3_reduce": "insights", "ig3_merge": "groups", "ig3_check": "links"}
FREE_FORM = {"domain", "dedup", "sten", "sten_sum", "ig3_map", "ig3_reduce", "ig3_merge", "ig3_check"}
LOW_REASONING = {"reasoning_effort": "low"}  # слияние ИГ3: полное рассуждение не помещается в лимит Cloud.ru 32k

# Журнал вызовов: (step, model, tokens_in, tokens_out, seconds, ok, error) → запись в БД делает вызывающий
CallLogger = Callable[[str, str, int, int, float, bool, str | None], Awaitable[None]]


class LlmError(RuntimeError):
    pass


def parse_json(text: str) -> Any:
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise
        return json.loads(t[a:b + 1])


def validate(step: str, obj: Any) -> list[str]:
    """Ошибки формата ответа (пусто — формат верен)."""
    if not isinstance(obj, dict) or RESULT_KEY[step] not in obj:
        return [f"нет поля {RESULT_KEY[step]}"]
    if step in FREE_FORM:
        return []
    errs: list[str] = []
    items = obj[RESULT_KEY[step]]
    if not isinstance(items, list):
        return [f"{RESULT_KEY[step]} не список"]
    for it in items:
        if step == "0":
            if not it.get("parts"):
                errs.append(f"{it.get('component_id')}: нет parts")
            errs += [f"quantifier={p.get('quantifier')}" for p in it.get("parts", [])
                     if p.get("quantifier") not in ENUMS["quantifier"]]
        elif step == "4":
            errs += [f"{f}={it.get(f)}" for f in ("subject", "kind", "period") if it.get(f) not in ENUMS[f]]
        elif step == "5" and it.get("label") not in ENUMS["label"]:
            errs.append(f"label={it.get('label')}")
    return errs


class Llm:
    def __init__(self, log: CallLogger | None = None) -> None:
        s = get_settings()
        if not s.cloudru_api_key:
            raise LlmError("Нет CLOUDRU_API_KEY: проверьте iCust.env (SECRETS_ENV_FILE)")
        self.model = s.llm_model
        self.log = log
        self.client = httpx.AsyncClient(
            base_url=s.cloudru_base_url,
            headers={"Authorization": f"Bearer {s.cloudru_api_key.get_secret_value()}"},
            timeout=httpx.Timeout(900, connect=30),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        """Запрос с повторами при временных сбоях: сеть/DNS, 429, 5xx. 14.11.2026 кратковременная потеря DNS
        за секунды уронила шаг 5 трёх интервью — теперь ждём до ~4 минут, прежде чем считать это ошибкой."""
        for pause in (*NET_RETRY_PAUSES, None):
            try:
                r = await self.client.post("/chat/completions", json=body)
                if r.status_code != 429 and r.status_code < 500:
                    return r
                if pause is None:
                    return r
            except httpx.TransportError:
                if pause is None:
                    raise
            await asyncio.sleep(pause)
        raise AssertionError("недостижимо")

    async def _complete(self, step: str, system: str, user: str, thinking: bool,
                        extra: dict[str, Any] | None = None) -> tuple[str, str | None]:
        body: dict[str, Any] = {
            "model": self.model, "temperature": 0.0, "max_tokens": 32000,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        if not thinking:
            body.update(NO_THINKING)
        body.update(extra or {})
        t0 = time.monotonic()
        tokens_in = tokens_out = 0
        try:
            r = await self._post(body)
            if r.status_code == 400 and "response_format" in r.text:  # часть моделей не принимает json-режим
                body.pop("response_format")
                r = await self._post(body)
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            tokens_in, tokens_out = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
            if self.log:
                await self.log(step, self.model, tokens_in, tokens_out, time.monotonic() - t0, True, None)
            return text, choice.get("finish_reason")
        except Exception as e:
            if self.log:
                await self.log(step, self.model, tokens_in, tokens_out, time.monotonic() - t0, False, repr(e)[:500])
            raise

    async def call(self, step: str, system: str, user: str, thinking: bool = False, retries: int = 1,
                   extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Один запрос с повтором при ошибке формата. Возвращает разобранный JSON."""
        last: str = ""
        for _ in range(retries + 1):
            try:
                text, _finish = await self._complete(step, system, user, thinking, extra)
                obj = parse_json(text)
                errs = validate(step, obj)
                if not errs:
                    return obj  # type: ignore[no-any-return]
                last = "; ".join(errs[:5])
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
                last = repr(e)[:300]
        raise LlmError(f"шаг {step}: {last}")

    async def chunked(self, step: str, project: dict[str, Any], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Шаги 3б/4 по кускам интервью; результат — только по целевым репликам каждого куска."""
        key, role = ("turns", "interviewer") if step == "3b" else ("claims", "respondent")
        system = P.SYSTEM[step] + P.CHUNK_NOTE[step]
        builder = P.user_3b_chunk if step == "3b" else P.user_4_chunk
        items: list[dict[str, Any]] = []

        async def process(a: int, b: int) -> None:
            head = turns[:min(HEAD_TURNS, a)]
            ctx = turns[max(len(head), a - OVERLAP_TURNS):a]
            target = turns[a:b]
            try:
                obj = await self.call(step, system, builder(project, head, ctx, target))
            except LlmError:
                if b - a > MIN_SPLIT:  # не уложился или не разобрался — делим пополам
                    mid = (a + b) // 2
                    await process(a, mid)
                    await process(mid, b)
                    return
                raise
            own = {t["turn_index"] for t in target if t["speaker_role"] == role}
            items.extend(x for x in obj.get(key, []) if x.get("turn_index") in own)

        for a, b in chunk_bounds(turns):
            await process(a, b)
        items.sort(key=lambda x: x.get("turn_index", 0))
        return items


def chunk_bounds(turns: list[dict[str, Any]], size: int = CHUNK_TURNS) -> list[tuple[int, int]]:
    """Границы кусков: ~size реплик, кусок начинается с реплики интервьюера (если такая есть рядом)."""
    n, start, out = len(turns), 0, []
    while start < n:
        end = min(start + size, n)
        if end < n:
            cand = [i for i in range(start + size // 2, end + 1) if turns[i]["speaker_role"] == "interviewer"]
            end = cand[-1] if cand else end
        out.append((start, end))
        start = end
    return out
