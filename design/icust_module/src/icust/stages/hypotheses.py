"""Этап 2. Гипотезы ценности продукта.

По каждому сегменту — отдельный цикл, сегменты параллельно. Примеры — те же 4 экспертных сегмента, что отбирает
retrieval на этапе сегментов, под каждым — его экспертные гипотезы. Цикл как у сегментов: до 3 генераций,
первые 2 прошедшие по порядку генераций, добор лучшими непрошедшими этого же сегмента.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np

from .. import config
from ..common import add_interview_block, clean_segment, crit_block, format_context, product_to_row, verdict_obj, yes_no
from ..extraction import extract_hypothesis_elements
from ..knowledge_base import KnowledgeBase, find_leak_case, is_duplicate, select_examples
from ..llm import Meta, llm_call

HYP_FORMULA = ("Наш продукт [{А}] помогает [роли {Б}], которые [в ситуации {Б2}], решить [проблему {В}], "
               "приводящую к [потерям {В1}], чтобы [выполнить задачу {Б1}] за счёт [функции {Г}] "
               "и достичь [результата {Д}] с [эффектом {Д1}].")

HYP_USER_TEMPLATE = ("Примеры экспертных гипотез ценности для других продуктов:\n\n{examples}\n\n---\n\n"
                     "Описание продукта:\n{query_context}\n\n"
                     "Сегмент, для которого нужно сформулировать {n_items} гипотезы ценности:\n{segment}")

JUDGE_HYP_USER_TEMPLATE = ("{judge_examples}\n\n---\n\nОцени гипотезы ценности.\n\nОписание продукта:\n{query_context}"
                           "\n\nСегмент: {segment}\n\nГипотезы ценности:\n{items}")

HYP_MIN_LEN, HYP_MAX_LEN = 120, 2000

HYP_SCHEMA = {
    "name": "value_hypotheses",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "hypotheses": {"type": "array", "items": {"type": "string"},
                           "minItems": config.N_HYP_PER_SEGMENT, "maxItems": config.N_HYP_PER_SEGMENT},
        },
        "required": ["hypotheses"],
        "additionalProperties": False,
    },
}


def _prompts(kb: KnowledgeBase) -> SimpleNamespace:
    """Промпты генератора и оценщика: критерии 1–6 (без критериев «после интервью») из разметки базы."""
    if "hypotheses" in kb.cache:
        return kb.cache["hypotheses"]
    crit = (kb.evals[(kb.evals["kind"] == "hyp") & (~kb.evals["post_interview"])]
            .drop_duplicates("criterion_no").sort_values("criterion_no")
            [["criterion_no", "criterion", "check"]])
    system_gen = f"""Ты — эксперт по CustDev-исследованиям. По описанию продукта и гипотезе о сегменте целевой аудитории ты формулируешь гипотезы ценности продукта для этого сегмента.

Каждая гипотеза — одно предложение строго по формуле:
{HYP_FORMULA}

Требования к каждой гипотезе:
{chr(10).join(f"{r.criterion_no}. {r.criterion}" for r in crit.itertuples())}

Примеры могут отличаться от формулы по форме — формулу соблюдай строго.

Сформулируй ровно {config.N_HYP_PER_SEGMENT} гипотезы ценности для заданного сегмента. Гипотезы должны содержательно различаться между собой. Если в описании продукта нет проверяемого эффекта {{Д1}}, заканчивай гипотезу без части «с [эффектом]». Опирайся только на сведения из описания продукта и гипотезы сегмента, не добавляй неподтверждённых обстоятельств. Пиши на русском языке."""

    system_judge = f"""Ты — эксперт по CustDev-исследованиям и проверяешь гипотезы ценности продукта по чек-листу.

Тебе дают описание продукта (исходные данные пользователя), гипотезу о сегменте целевой аудитории и гипотезы ценности продукта для этого сегмента. Оцени каждую гипотезу ценности по критериям.

Правила:
— Критерий выполнен (verdict = true), только если выполнены ВСЕ пункты «Что проверяем». Если хотя бы один пункт не выполнен — false.
— Сначала кратко (1–3 предложения) обоснуй оценку в поле reason, ссылаясь на текст гипотезы, сегмента и поля описания, затем поставь verdict.
— Сверяй гипотезы только с описанием продукта и гипотезой сегмента, ничего не додумывай.
— Ориентируйся на строгость эксперта из примера оценки.

КРИТЕРИИ:

{crit_block(crit)}"""
    p = SimpleNamespace(system_gen=system_gen, system_judge=system_judge, item_nos=crit["criterion_no"].tolist())
    kb.cache["hypotheses"] = p
    return p


def hypothesis_problems(data) -> list[str]:
    if data is None:
        return ["ответ не разобран как JSON"]
    hyps = [clean_segment(h) for h in data.get("hypotheses", [])]
    probs = []
    if len(hyps) != config.N_HYP_PER_SEGMENT:
        probs.append(f"гипотез {len(hyps)} вместо {config.N_HYP_PER_SEGMENT}")
    if len(set(hyps)) < len(hyps):
        probs.append("есть одинаковые гипотезы")
    for i, h in enumerate(hyps, 1):
        if "\n" in h:
            probs.append(f"#{i}: перенос строки — похоже, несколько гипотез в одной")
        if len(h) < HYP_MIN_LEN:
            probs.append(f"#{i}: слишком короткая ({len(h)} симв.)")
        elif len(h) > HYP_MAX_LEN:
            probs.append(f"#{i}: слишком длинная ({len(h)} симв.)")
    return probs


def validate_hypotheses(data) -> bool:
    return not hypothesis_problems(data)


def format_hyp_examples(segment_ids: list[str], kb: KnowledgeBase) -> str:
    """Примеры по кейсам: контекст кейса один раз, под ним — сегменты и под каждым все его валидные гипотезы."""
    segs = kb.seg_base.set_index("segment_id").loc[segment_ids].reset_index()
    blocks = []
    for i, (case_id, g) in enumerate(segs.groupby("case_id", sort=False), start=1):
        parts = [f"### Пример {i}\nОписание продукта:\n{kb.ctx_by_case[case_id]}"]
        for r in g.itertuples():
            hyps = kb.hyp_base[(kb.hyp_base["segment_id"] == r.segment_id) & kb.hyp_base["valid"]].sort_values("hypothesis_id")
            hyp_lines = "\n".join(f"{j}. {t}" for j, t in enumerate(hyps["text"], start=1))
            parts.append(f"Сегмент: {r.text}\nГипотезы ценности:\n{hyp_lines}")
        blocks.append("\n\n".join(parts))
    return "\n\n".join(blocks)


def judge_schema_hyp(n_hyps: int, p: SimpleNamespace) -> dict:
    return {
        "name": "hypothesis_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "hypotheses": {
                    "type": "array", "minItems": n_hyps, "maxItems": n_hyps,
                    "items": {"type": "object",
                              "properties": {"hypothesis_no": {"type": "integer"},
                                             "criteria": {"type": "array", "items": verdict_obj(),
                                                          "minItems": len(p.item_nos), "maxItems": len(p.item_nos)}},
                              "required": ["hypothesis_no", "criteria"],
                              "additionalProperties": False},
                },
            },
            "required": ["hypotheses"],
            "additionalProperties": False,
        },
    }


def format_judge_example_hyp(case_id: str, kb: KnowledgeBase) -> str:
    """Экспертная оценка гипотез кейса: по каждому сегменту — его гипотезы и вердикты с комментариями."""
    ev = kb.evals[(kb.evals["kind"] == "hyp") & (kb.evals["case_id"] == case_id) & (~kb.evals["post_interview"])]
    parts = [f"### Пример экспертной оценки\nОписание продукта:\n{kb.ctx_by_case[case_id]}"]
    for seg in kb.seg_base[kb.seg_base["case_id"] == case_id].sort_values("segment_id").itertuples():
        hyps = kb.hyp_base[kb.hyp_base["segment_id"] == seg.segment_id].sort_values("hypothesis_id")
        hyp_lines = "\n".join(f"{j}. {t}" for j, t in enumerate(hyps["text"], start=1))
        block = [f"Сегмент: {seg.text}\nГипотезы ценности:\n{hyp_lines}\n\nОценка:"]
        for j, hid in enumerate(hyps["hypothesis_id"], start=1):
            rows = ev[ev["entity_id"] == hid].sort_values("criterion_no")
            block.append(f"Гипотеза {j}:\n" + "\n".join(
                f"- Критерий {r.criterion_no}: {yes_no(r.verdict)}. {r.comment or ''}".rstrip() for r in rows.itertuples()))
        parts.append("\n\n".join(block))
    return "\n\n".join(parts)


def judge_problems_hyp(data, n_hyps: int, p: SimpleNamespace) -> list[str]:
    if data is None:
        return ["ответ не разобран как JSON"]
    probs = []
    hs = data.get("hypotheses", [])
    if len(hs) != n_hyps:
        probs.append(f"оценено гипотез {len(hs)} вместо {n_hyps}")
    for i, h in enumerate(hs, 1):
        nos = sorted(c.get("criterion_no") for c in h.get("criteria", []))
        if nos != p.item_nos:
            probs.append(f"гипотеза {i}: критерии {nos} вместо {p.item_nos}")
    return probs


def _hypotheses_for_segment(segment, query_ctx, examples_text, judge_case, dedupe, initial_generation,
                            interview_summary, meta, kb: KnowledgeBase):
    """Цикл по одному сегменту: до 3 генераций, первые 2 прошедшие, добор лучшими непрошедшими."""
    p = _prompts(kb)
    n_need = config.N_HYP_PER_SEGMENT
    user = HYP_USER_TEMPLATE.format(examples=examples_text, query_context=query_ctx,
                                    n_items=n_need, segment=segment["text"])
    user = add_interview_block(user, initial_generation, interview_summary)
    messages = [{"role": "system", "content": p.system_gen}, {"role": "user", "content": user}]
    judge_examples = format_judge_example_hyp(judge_case, kb)
    taken, rest = [], []
    for g in range(config.MAX_GENERATIONS):
        hyps = None
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            res = llm_call(config.GEN_MODEL, messages, schema=HYP_SCHEMA, temperature=config.GEN_TEMPERATURE,
                           sample_idx=g, validate=validate_hypotheses)
            meta.add(res["call"])
            if res["valid"]:
                hyps = [clean_segment(h) for h in res["data"]["hypotheses"]]
                break
            if res["error"]:
                break
        if hyps is None:
            meta.warn(f"{segment['segment_id']}, генерация {g + 1}: невалидный ответ")
            continue
        n = len(hyps)
        juser = JUDGE_HYP_USER_TEMPLATE.format(judge_examples=judge_examples, query_context=query_ctx,
                                               segment=segment["text"],
                                               items="\n".join(f"{i}. {h}" for i, h in enumerate(hyps, 1)))
        jmsgs = [{"role": "system", "content": p.system_judge}, {"role": "user", "content": juser}]
        checks = None
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            jr = llm_call(config.JUDGE_MODEL, jmsgs, schema=judge_schema_hyp(n, p), temperature=config.JUDGE_TEMPERATURE,
                          validate=lambda d: not judge_problems_hyp(d, n, p))
            meta.add(jr["call"])
            if jr["valid"]:
                checks = []
                for h in jr["data"]["hypotheses"]:
                    crit = h["criteria"]
                    checks.append({"passed": all(c["verdict"] for c in crit),
                                   "share": float(np.mean([c["verdict"] for c in crit])),
                                   "failed_criteria": [{"criterion_no": c["criterion_no"], "passed": False,
                                                        "reason": c["reason"]} for c in crit if not c["verdict"]]})
                break
            if jr["error"]:
                break
        if checks is None:
            meta.warn(f"{segment['segment_id']}, генерация {g + 1}: оценщик не вернул валидный ответ")
            continue
        for h, ch in zip(hyps, checks):
            if ch["passed"]:
                if len(taken) < n_need and not (dedupe and is_duplicate(h, [t for t, _ in taken], kb)):
                    taken.append((h, ch))
            else:
                rest.append((h, ch))
        if len(taken) >= n_need:
            break
    complete = len(taken) >= n_need
    chosen = list(taken)
    if not complete:
        for h, ch in sorted(rest, key=lambda x: -x[1]["share"]):
            if len(chosen) >= n_need:
                break
            if dedupe and is_duplicate(h, [t for t, _ in chosen], kb):
                continue
            chosen.append((h, ch))
        meta.warn(f"{segment['segment_id']}: прошли проверку {len(taken)} из {n_need} гипотез; "
                  "остальные добраны лучшими непрошедшими")
    return chosen, complete


def generate_value_hypotheses(product: dict, segments: list[dict], kb: KnowledgeBase, n_per_segment: int = 2,
                              dedupe: bool = False, initial_generation: bool = True,
                              interview_summary: dict | None = None) -> dict:
    """Этап 2. segments — сегменты из ответа этапа 1. Ответ по контракту HypothesesResponse."""
    if n_per_segment != config.N_HYP_PER_SEGMENT:
        raise ValueError("n_per_segment: пока поддерживается только 2")
    _prompts(kb)                                                   # собрать промпты до запуска потоков
    row = product_to_row(product)
    query_ctx = format_context(row)
    q_key = format_context(row, exclude=("product",))
    leak = find_leak_case(row, kb)
    exclude = {leak} if leak else set()
    example_ids = select_examples(q_key, kb, exclude=exclude)      # те же примеры, что на этапе сегментов
    examples_text = format_hyp_examples(example_ids, kb)
    judge_case = config.pick_example(config.JUDGE_EXAMPLE_HYP, leak)

    metas = [Meta() for _ in segments]
    with ThreadPoolExecutor(max_workers=max(1, len(segments))) as ex:
        futs = [ex.submit(_hypotheses_for_segment, s, query_ctx, examples_text, judge_case, dedupe,
                          initial_generation, interview_summary, m, kb) for s, m in zip(segments, metas)]
        results = [f.result() for f in futs]

    meta = Meta()
    hypotheses, complete, k = [], True, 0
    for seg, (chosen, ok), m in zip(segments, results, metas):
        complete &= ok
        for h, ch in chosen:
            k += 1
            elements, verified = extract_hypothesis_elements(h, m)
            hypotheses.append({"hypothesis_id": f"H{k:02d}", "segment_id": seg["segment_id"], "text": h,
                               "elements": elements, "elements_verified": verified,
                               "check": {"passed": ch["passed"], "failed_criteria": ch["failed_criteria"]}})
    for m in metas:
        meta.merge(m)
    return {"hypotheses": hypotheses, "complete": complete,
            "message": None if complete else "Не все гипотезы прошли проверку по критериям: недостающие добраны лучшими из непрошедших.",
            "meta": meta.to_dict()}
