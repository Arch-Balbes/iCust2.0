"""Разбиение проверенного предложения (сегмента или гипотезы ценности) на элементы формулы.

LLM размечает элементы как дословные фрагменты; код проверяет, что фрагменты идут по порядку,
а между ними — только связки формулы. Попытки: t = 0.0, 0.7, 0.7. Если ни одна не прошла проверку —
возвращается лучшая попытка и elements_verified=False.
"""
from __future__ import annotations

import difflib
import re

from . import config
from .llm import Meta, llm_call

FORBIDDEN_START = r"(?:котор\w*|стрем\w*|хотят|чтобы)\b"   # элемент не может начинаться со связки формулы

# ---------------------------------------------------------------- сегмент: [Б], которые [Б2] стремятся [Б1], чтобы [Д]
SEG_ELEMENTS = ["role", "situation", "job", "outcome"]
SEG_GAPS = [r"", r"[,\s\-–—]*(?:котор\w*)?", r"[,\s\-–—]*(?:стрем\w*|хот\w*)?", r"[,\s\-–—]*чтобы"]   # что допустимо ПЕРЕД элементом
SEG_CONNECTORS = ["", ", которые ", " стремятся ", ", чтобы "]        # связки формулы для сборки обратно

SYSTEM_PROMPT_EXTRACT_SEG = """Ты размечаешь готовую гипотезу о сегменте целевой аудитории по элементам формулы:
[role — группа потребителей в определённой роли], которые [situation — ситуация и условия] стремятся [job — потребительская задача], чтобы [outcome — объединяющий желаемый результат]

Правила:
— Каждый элемент — дословный непрерывный фрагмент исходного предложения. Не переписывай, не сокращай, не меняй слова, падежи и знаки препинания.
— Связки «которые», «стремятся» (или другой глагол на этом месте, например «хотят»), «чтобы» и запятые или тире перед ними в элементы не включай.
— Элементы идут в предложении в порядке role, situation, job, outcome и вместе со связками покрывают всё предложение.
— Точку в конце предложения в элементы не включай."""

SEG_EXTRACT_SCHEMA = {
    "name": "segment_elements", "strict": True,
    "schema": {"type": "object",
               "properties": {k: {"type": "string"} for k in SEG_ELEMENTS},
               "required": SEG_ELEMENTS, "additionalProperties": False},
}

# ---------------------------------------------------------------- гипотеза ценности (формула реестра)
HYP_ELEMENTS = ["product", "role", "situation", "problem", "losses", "job", "mechanism", "outcome", "effect"]
HYP_GAPS = [r"Наш\s+продукт",
            r"помогает",
            r"[,\s\-–—]*(?:котор\w*)?",
            r"[,\s\-–—]*решить(?:\s+проблему:?)?",
            r"[,\s\-–—]*приводящ\w*\s+к(?:\s+потерям:?|\s+тому,?\s+что)?",
            r"[,\s\-–—]*чтобы(?:\s+выполнить\s+задачу:?)?",
            r"[,\s\-–—]*за\s+сч[её]т(?:\s+того,?\s+что)?",
            r"[,\s\-–—]*и\s+достичь(?:\s+результата:?|\s+того,?\s+чтобы)?",
            r"[,\s\-–—]*с(?:\s+эффектом:?)?"]
HYP_CONNECTORS = ["Наш продукт ", " помогает ", ", которые ", ", решить ", ", приводящую к ", ", чтобы ",
                  " за счёт ", " и достичь ", " с "]

SYSTEM_PROMPT_EXTRACT_HYP = """Ты размечаешь готовую гипотезу ценности продукта по элементам формулы:
Наш продукт [product] помогает [role], которые [situation], решить [problem], приводящую к [losses], чтобы [job] за счёт [mechanism] и достичь [outcome] с [effect].

Где: product — продукт; role — роль потребителей; situation — ситуация и условия; problem — проблема; losses — потери; job — потребительская задача; mechanism — функция продукта; outcome — результат; effect — измеримый эффект.

Правила:
— Каждый элемент — дословный непрерывный фрагмент исходного предложения. Не переписывай, не сокращай, не меняй слова, падежи и знаки препинания.
— Слова формулы в элементы не включай: «Наш продукт», «помогает», «которые», «решить», «проблему:», «приводящую к», «потерям», «тому, что», «чтобы», «выполнить задачу», «за счёт», «того, что», «и достичь», «результата:», «того, чтобы», «с», «эффектом:», а также запятые и тире перед ними.
— Элементы идут в предложении в указанном порядке и вместе со словами формулы покрывают всё предложение.
— Если в предложении нет части с эффектом, верни для effect пустую строку.
— Точку в конце предложения в элементы не включай."""

HYP_EXTRACT_SCHEMA = {
    "name": "hypothesis_elements", "strict": True,
    "schema": {"type": "object",
               "properties": {k: {"type": "string"} for k in HYP_ELEMENTS},
               "required": HYP_ELEMENTS, "additionalProperties": False},
}


def check_elements(text: str, elements: dict, order, gaps, connectors) -> tuple[bool, int, float]:
    """Проверка разбиения. Возвращает (verified, n_verbatim, similarity)."""
    t = re.sub(r"\s+", " ", text).strip()
    vals = [re.sub(r"\s+", " ", str(elements.get(k) or "")).strip() for k in order]
    n_verbatim = sum(1 for v in vals if v and v in t)
    pos, ok = 0, all(vals) and not any(re.match(FORBIDDEN_START, v, re.I) for v in vals)
    for v, gap in zip(vals, gaps):
        i = t.find(v, pos) if v else -1
        if i < 0 or not re.fullmatch(rf"\s*{gap}\s*" if gap else r"\s*", t[pos:i]):
            ok = False
            break
        pos = i + len(v)
    ok = ok and re.fullmatch(r"[\s.]*", t[pos:]) is not None
    rebuilt = "".join(c + v for c, v in zip(connectors, vals))
    sim = difflib.SequenceMatcher(None, re.sub(r"[^\w]+", " ", t).lower(), re.sub(r"[^\w]+", " ", rebuilt).lower(),
                                  autojunk=False).ratio()
    return ok, n_verbatim, sim


def extract_segment_elements(text: str, meta: Meta) -> tuple[dict, bool]:
    """Элементы сегмента (role, situation, job, outcome) и признак проверенного дословного разбиения."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT_EXTRACT_SEG}, {"role": "user", "content": f"Предложение:\n{text}"}]
    best, best_key = None, None
    for attempt, temp in enumerate(config.EXTRACT_TEMPERATURES):
        res = llm_call(config.GEN_MODEL, msgs, schema=SEG_EXTRACT_SCHEMA, temperature=temp, sample_idx=attempt)
        meta.add(res["call"])
        if not res["valid"]:
            continue
        ok, n_verb, sim = check_elements(text, res["data"], SEG_ELEMENTS, SEG_GAPS, SEG_CONNECTORS)
        filled = all(str(res["data"].get(k) or "").strip() for k in SEG_ELEMENTS)
        key = (ok, filled, n_verb, sim)
        if best_key is None or key > best_key:
            best, best_key = res["data"], key
        if ok:
            break
    if best is None:
        meta.warn(f"не удалось разбить на элементы: {text[:60]}…")
        return {k: None for k in SEG_ELEMENTS}, False
    if not best_key[0]:
        meta.warn(f"разбиение не дословное: {text[:60]}…")
    return {k: best.get(k) for k in SEG_ELEMENTS}, bool(best_key[0])


def extract_hypothesis_elements(text: str, meta: Meta) -> tuple[dict, bool]:
    """Элементы гипотезы ценности (9 полей); без эффекта — проверка по первым 8, effect = None."""
    msgs = [{"role": "system", "content": SYSTEM_PROMPT_EXTRACT_HYP}, {"role": "user", "content": f"Предложение:\n{text}"}]
    best, best_key = None, None
    for attempt, temp in enumerate(config.EXTRACT_TEMPERATURES):
        res = llm_call(config.GEN_MODEL, msgs, schema=HYP_EXTRACT_SCHEMA, temperature=temp, sample_idx=attempt)
        meta.add(res["call"])
        if not res["valid"]:
            continue
        data = res["data"]
        n = 9 if str(data.get("effect") or "").strip() else 8
        ok, n_verb, sim = check_elements(text, data, HYP_ELEMENTS[:n], HYP_GAPS[:n], HYP_CONNECTORS[:n])
        filled = all(str(data.get(k) or "").strip() for k in HYP_ELEMENTS[:n])
        key = (ok, filled, n_verb, sim)
        if best_key is None or key > best_key:
            best, best_key = data, key
        if ok:
            break
    if best is None:
        meta.warn(f"не удалось разбить на элементы: {text[:60]}…")
        return {k: None for k in HYP_ELEMENTS}, False
    if not best_key[0]:
        meta.warn(f"разбиение не дословное: {text[:60]}…")
    return {k: (str(best.get(k) or "").strip() or None) for k in HYP_ELEMENTS}, bool(best_key[0])
