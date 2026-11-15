"""Этап 1. Гипотезы сегментов ЦА.

Цикл (как в эксперименте, конфигурация 5): до 3 генераций одним промптом -> оценщик -> сегменты, прошедшие
все критерии, берутся по порядку генераций -> стоп при 3 прошедших -> после 3-й генерации нехватка добирается
лучшими непрошедшими по доле выполненных критериев. Затем разбиение на элементы формулы.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import numpy as np

from .. import config
from ..common import (add_interview_block, clean_segment, crit_block, format_context, product_to_row, verdict_obj,
                      yes_no)
from ..extraction import extract_segment_elements
from ..knowledge_base import KnowledgeBase, find_leak_case, is_duplicate, select_examples
from ..llm import Meta, llm_call

SEG_FORMULA = ("[Группа потребителей в определённой роли — {Б}], которые [в ситуации и условиях — {Б2}] "
               "стремятся [выполнить потребительскую задачу — {Б1}], чтобы [достичь объединяющего желаемого результата — {Д}]")

SEG_USER_TEMPLATE = ("Примеры экспертных сегментаций для других продуктов:\n\n{examples}\n\n---\n\n"
                     "Описание продукта, для которого нужно сформулировать {n_items} сегмента:\n{query_context}")

JUDGE_USER_TEMPLATE = ("{judge_examples}\n\n---\n\nОцени набор сегментов.\n\nОписание продукта:\n{query_context}"
                       "\n\nСегменты:\n{items}")

SEG_MIN_LEN, SEG_MAX_LEN = 80, 1200

SEG_SCHEMA = {
    "name": "segments",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {"type": "string"},
                         "minItems": config.N_SEGMENTS, "maxItems": config.N_SEGMENTS},
        },
        "required": ["segments"],
        "additionalProperties": False,
    },
}


def _prompts(kb: KnowledgeBase) -> SimpleNamespace:
    """Промпты генератора и оценщика: критерии берутся из разметки базы (один раз на базу)."""
    if "segments" in kb.cache:
        return kb.cache["segments"]
    crit = (kb.evals[kb.evals["kind"] == "seg"]
            .drop_duplicates("criterion_no").sort_values("criterion_no")
            [["criterion_no", "criterion", "check", "level"]])
    item_rows, gen_rows = crit[crit["level"] == "item"], crit[crit["level"] != "item"]
    system_gen = f"""Ты — эксперт по CustDev-исследованиям. По описанию продукта ты формулируешь гипотезы о сегментах целевой аудитории для проблемных интервью.

Каждый сегмент — одно предложение строго по формуле:
{SEG_FORMULA}

Требования к каждому сегменту:
{chr(10).join(f"{r.criterion_no}. {r.criterion}" for r in item_rows.itertuples())}

Требования к набору сегментов в целом:
{chr(10).join(f"{r.criterion_no}. {r.criterion}" for r in gen_rows.itertuples())}

Сформулируй ровно {config.N_SEGMENTS} сегмента. Сегменты должны содержательно различаться между собой. Опирайся только на сведения из описания продукта, не добавляй неподтверждённых обстоятельств. Пиши на русском языке."""

    system_judge = f"""Ты — эксперт по CustDev-исследованиям и проверяешь гипотезы о сегментах целевой аудитории по чек-листу.

Тебе дают описание продукта (исходные данные пользователя) и набор сегментов. Оцени:
— каждый сегмент по критериям уровня сегмента;
— весь набор сегментов целиком по критериям уровня генерации.

Правила:
— Критерий выполнен (verdict = true), только если выполнены ВСЕ пункты «Что проверяем». Если хотя бы один пункт не выполнен — false.
— Сначала кратко (1–3 предложения) обоснуй оценку в поле reason, ссылаясь на текст сегмента и поля описания, затем поставь verdict.
— Сверяй сегменты только с описанием продукта, ничего не додумывай.
— Ориентируйся на строгость эксперта из примера оценки.

КРИТЕРИИ УРОВНЯ СЕГМЕНТА:

{crit_block(item_rows)}

КРИТЕРИИ УРОВНЯ ГЕНЕРАЦИИ (оцениваются один раз для всего набора):

{crit_block(gen_rows)}"""
    p = SimpleNamespace(system_gen=system_gen, system_judge=system_judge,
                        item_nos=item_rows["criterion_no"].tolist(), gen_nos=gen_rows["criterion_no"].tolist())
    kb.cache["segments"] = p
    return p


def segment_problems(data) -> list[str]:
    if data is None:
        return ["ответ не разобран как JSON"]
    segs = [clean_segment(s) for s in data.get("segments", [])]
    probs = []
    if len(segs) != config.N_SEGMENTS:
        probs.append(f"сегментов {len(segs)} вместо {config.N_SEGMENTS}")
    if len(set(segs)) < len(segs):
        probs.append("есть одинаковые сегменты")
    for i, s in enumerate(segs, 1):
        if "\n" in s:
            probs.append(f"#{i}: перенос строки — похоже, несколько сегментов в одном")
        if re.fullmatch(r"[\w\s]+_[\w_]+", s):
            probs.append(f"#{i}: служебная строка {s!r}")
        elif len(s) < SEG_MIN_LEN:
            probs.append(f"#{i}: слишком короткий ({len(s)} симв.)")
        elif len(s) > SEG_MAX_LEN:
            probs.append(f"#{i}: слишком длинный ({len(s)} симв.)")
    return probs


def validate_segments(data) -> bool:
    return not segment_problems(data)


def format_examples(segment_ids: list[str], kb: KnowledgeBase) -> str:
    """Примеры, сгруппированные по кейсам: контекст кейса один раз, под ним его сегменты."""
    segs = kb.seg_base.set_index("segment_id").loc[segment_ids].reset_index()
    blocks = []
    for i, (case_id, g) in enumerate(segs.groupby("case_id", sort=False), start=1):
        seg_lines = "\n".join(f"{j}. {t}" for j, t in enumerate(g["text"], start=1))
        blocks.append(f"### Пример {i}\nОписание продукта:\n{kb.ctx_by_case[case_id]}\n\nСегменты:\n{seg_lines}")
    return "\n\n".join(blocks)


def judge_schema(n_segments: int, p: SimpleNamespace) -> dict:
    return {
        "name": "segment_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array", "minItems": n_segments, "maxItems": n_segments,
                    "items": {"type": "object",
                              "properties": {"segment_no": {"type": "integer"},
                                             "criteria": {"type": "array", "items": verdict_obj(),
                                                          "minItems": len(p.item_nos), "maxItems": len(p.item_nos)}},
                              "required": ["segment_no", "criteria"],
                              "additionalProperties": False},
                },
                "generation_criteria": {"type": "array", "items": verdict_obj(),
                                        "minItems": len(p.gen_nos), "maxItems": len(p.gen_nos)},
            },
            "required": ["segments", "generation_criteria"],
            "additionalProperties": False,
        },
    }


def format_judge_example(case_id: str, kb: KnowledgeBase) -> str:
    ctx = kb.ctx_by_case[case_id]
    segs = kb.seg_base[kb.seg_base["case_id"] == case_id].sort_values("segment_id")
    ev = kb.evals[(kb.evals["kind"] == "seg") & (kb.evals["case_id"] == case_id)]
    seg_lines = "\n".join(f"{i}. {t}" for i, t in enumerate(segs["text"], 1))
    parts = [f"### Пример экспертной оценки\nОписание продукта:\n{ctx}\n\nСегменты:\n{seg_lines}\n\nОценка:"]
    for i, sid in enumerate(segs["segment_id"], 1):
        rows = ev[(ev["entity_id"] == sid) & (ev["level"] == "item")].sort_values("criterion_no")
        parts.append(f"Сегмент {i}:\n" + "\n".join(
            f"- Критерий {r.criterion_no}: {yes_no(r.verdict)}. {r.comment or ''}".rstrip() for r in rows.itertuples()))
    gen = ev[ev["level"] != "item"].drop_duplicates("criterion_no").sort_values("criterion_no")
    parts.append("Набор сегментов целиком:\n" + "\n".join(
        f"- Критерий {r.criterion_no}: {yes_no(r.verdict)}. {r.comment or ''}".rstrip() for r in gen.itertuples()))
    return "\n\n".join(parts)


def judge_problems(data, n_segments: int, p: SimpleNamespace) -> list[str]:
    if data is None:
        return ["ответ не разобран как JSON"]
    probs = []
    segs = data.get("segments", [])
    if len(segs) != n_segments:
        probs.append(f"оценено сегментов {len(segs)} вместо {n_segments}")
    for i, s in enumerate(segs, 1):
        nos = sorted(c.get("criterion_no") for c in s.get("criteria", []))
        if nos != p.item_nos:
            probs.append(f"сегмент {i}: критерии {nos} вместо {p.item_nos}")
    gen_nos = sorted(c.get("criterion_no") for c in data.get("generation_criteria", []))
    if gen_nos != p.gen_nos:
        probs.append(f"набор: критерии {gen_nos} вместо {p.gen_nos}")
    return probs


def _generate_once(messages, sample_idx, meta) -> list[str] | None:
    """Одна генерация с повторами при невалидном ответе."""
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        res = llm_call(config.GEN_MODEL, messages, schema=SEG_SCHEMA, temperature=config.GEN_TEMPERATURE,
                       sample_idx=sample_idx, validate=validate_segments)
        meta.add(res["call"])
        if res["valid"]:
            return [clean_segment(s) for s in res["data"]["segments"]]
        if res["error"]:
            break
    meta.warn(f"генерация {sample_idx + 1}: невалидный ответ после {config.MAX_ATTEMPTS} попыток")
    return None


def _judge_once(query_ctx, segments, judge_case, meta, kb: KnowledgeBase) -> list[dict] | None:
    """Оценка набора: по каждому сегменту — прошёл ли, доля критериев, невыполненные критерии."""
    p = _prompts(kb)
    n = len(segments)
    user = JUDGE_USER_TEMPLATE.format(judge_examples=format_judge_example(judge_case, kb), query_context=query_ctx,
                                      items="\n".join(f"{i}. {s}" for i, s in enumerate(segments, 1)))
    msgs = [{"role": "system", "content": p.system_judge}, {"role": "user", "content": user}]
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        res = llm_call(config.JUDGE_MODEL, msgs, schema=judge_schema(n, p), temperature=config.JUDGE_TEMPERATURE,
                       validate=lambda d: not judge_problems(d, n, p))
        meta.add(res["call"])
        if res["valid"]:
            out = []
            for s in res["data"]["segments"]:
                crit = s["criteria"]
                out.append({"passed": all(c["verdict"] for c in crit),
                            "share": float(np.mean([c["verdict"] for c in crit])),
                            "failed_criteria": [{"criterion_no": c["criterion_no"], "passed": False,
                                                 "reason": c["reason"]} for c in crit if not c["verdict"]]})
            return out
        if res["error"]:
            break
    meta.warn("оценщик не вернул валидный ответ — сегменты этой генерации не учитываются")
    return None


def generate_segments(product: dict, kb: KnowledgeBase, n_segments: int = 3, dedupe: bool = False,
                      initial_generation: bool = True, interview_summary: dict | None = None) -> dict:
    """Этап 1. product — анкета (dict, groups — список). Возвращает ответ по контракту SegmentsResponse."""
    if n_segments != config.N_SEGMENTS:
        raise ValueError("n_segments: пока поддерживается только 3")
    p = _prompts(kb)
    meta = Meta()
    row = product_to_row(product)
    query_ctx = format_context(row)
    q_key = format_context(row, exclude=("product",))
    leak = find_leak_case(row, kb)
    exclude = {leak} if leak else set()
    example_ids = select_examples(q_key, kb, exclude=exclude)
    user = SEG_USER_TEMPLATE.format(examples=format_examples(example_ids, kb), n_items=config.N_SEGMENTS,
                                    query_context=query_ctx)
    user = add_interview_block(user, initial_generation, interview_summary)
    messages = [{"role": "system", "content": p.system_gen}, {"role": "user", "content": user}]
    judge_case = config.pick_example(config.JUDGE_EXAMPLE_SEG, leak)

    taken, rest = [], []           # taken: прошедшие; rest: непрошедшие (текст, проверка)
    for g in range(config.MAX_GENERATIONS):
        segs = _generate_once(messages, g, meta)
        if segs is None:
            continue
        checks = _judge_once(query_ctx, segs, judge_case, meta, kb)
        if checks is None:
            continue
        for s, ch in zip(segs, checks):
            if ch["passed"]:
                if len(taken) < n_segments and not (dedupe and is_duplicate(s, [t for t, _ in taken], kb)):
                    taken.append((s, ch))
            else:
                rest.append((s, ch))
        if len(taken) >= n_segments:
            break

    complete = len(taken) >= n_segments
    chosen = list(taken)
    if not complete:
        for s, ch in sorted(rest, key=lambda x: -x[1]["share"]):     # стабильная сортировка
            if len(chosen) >= n_segments:
                break
            if dedupe and is_duplicate(s, [t for t, _ in chosen], kb):
                continue
            chosen.append((s, ch))
        meta.warn(f"прошли проверку {len(taken)} из {n_segments} сегментов; остальные добраны лучшими непрошедшими")

    segments = []
    for i, (s, ch) in enumerate(chosen, 1):
        elements, verified = extract_segment_elements(s, meta)
        segments.append({"segment_id": f"SEG{i:02d}", "text": s, "elements": elements, "elements_verified": verified,
                         "check": {"passed": ch["passed"], "failed_criteria": ch["failed_criteria"]}})
    return {"segments": segments, "complete": complete,
            "message": None if complete else "Не все сегменты прошли проверку по критериям: недостающие добраны лучшими из непрошедших.",
            "meta": meta.to_dict()}
