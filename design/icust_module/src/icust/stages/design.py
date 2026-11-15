"""Этап 5. Дизайн исследования.

Раздел 1: название, ключевая функция и цель — из анкеты кодом ({А}, {Г}, {Ж}); три абзаца (проблема и потери,
текущие решения, желаемый результат) — один вызов генератора по шаблонам дизайна, только согласование
грамматики. Пример — раздел 1 дизайна C0008 (резерв C0010). Разделы 2–4 — результаты этапов кодом без изменений.
Документ (docx) собирает бэкенд.
"""
from __future__ import annotations

from .. import config
from ..common import format_context, product_to_row, strip_field_header
from ..knowledge_base import DESIGN_HEADINGS, KnowledgeBase, find_leak_case
from ..llm import Meta, llm_call

SYSTEM_PROMPT_DESIGN = """Ты — эксперт по CustDev-исследованиям. Ты заполняешь раздел «Описание продукта» дизайна исследования по шаблонам, подставляя поля анкеты.

Шаблоны (метки в фигурных скобках — поля анкеты):
— problem_and_losses: «{Б}, которые {Б2}, при {Б1} сталкиваются с проблемой {В}, что приводит к {В1}.»
— current_solutions: «Сейчас, чтобы {Б1}, {Б} {Е}, но это не решает проблему {В}.»
— desired_outcome_and_effect: «{Б} хотят {Д}, с {Д1} вместо {В1}.» Если поля {Д1} в анкете нет — без «с {Д1} вместо {В1}».

Правила:
— Бери содержание только из анкеты: меняй лишь грамматику (падеж, число, порядок слов), чтобы предложение читалось связно, как в примере.
— Не добавляй нового содержания и не выбрасывай существенного.
— Если групп в {Б} несколько — поступай как в примере.
— Пиши на русском языке."""

DESIGN_USER_TEMPLATE = ("Пример заполнения экспертом:\n\nАнкета:\n{ex_context}\n\n"
                        "problem_and_losses: {ex_problem}\n\ncurrent_solutions: {ex_current}\n\n"
                        "desired_outcome_and_effect: {ex_desired}\n\n---\n\nАнкета:\n{query_context}")

DESIGN_SCHEMA = {"name": "design_description", "strict": True,
                 "schema": {"type": "object",
                            "properties": {f: {"type": "string"} for f in DESIGN_HEADINGS},
                            "required": list(DESIGN_HEADINGS), "additionalProperties": False}}

# опорные фразы шаблонов, которые должны остаться в тексте
DESIGN_MARKERS = {"problem_and_losses": ["сталкиваются с проблемой", "приводит к"],
                  "current_solutions": ["Сейчас, чтобы", "но это не решает проблему"],
                  "desired_outcome_and_effect": ["хотят"]}


def design_problems(data) -> list[str]:
    if data is None:
        return ["ответ не разобран как JSON"]
    probs = []
    for f, markers in DESIGN_MARKERS.items():
        t = data.get(f) or ""
        if len(t.strip()) < 30:
            probs.append(f"{f}: пусто или слишком коротко")
        probs += [f"{f}: нет «{m}»" for m in markers if m not in t]
    return probs


def validate_design(data) -> bool:
    return not design_problems(data)


def build_design(product: dict, segments: list[dict], hypotheses: list[dict], scenarios: list[dict],
                 offers: list[dict], kb: KnowledgeBase) -> dict:
    """Этап 5. Ответ по контракту DesignResponse."""
    row = product_to_row(product)
    example_case = config.pick_example(config.DESIGN_EXAMPLE, find_leak_case(row, kb))
    ex = kb.design_examples[example_case]
    user = DESIGN_USER_TEMPLATE.format(ex_context=kb.ctx_by_case[example_case], ex_problem=ex["problem_and_losses"],
                                       ex_current=ex["current_solutions"], ex_desired=ex["desired_outcome_and_effect"],
                                       query_context=format_context(row))
    messages = [{"role": "system", "content": SYSTEM_PROMPT_DESIGN}, {"role": "user", "content": user}]
    meta, data = Meta(), None
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        res = llm_call(config.GEN_MODEL, messages, schema=DESIGN_SCHEMA, temperature=config.GEN_TEMPERATURE,
                       sample_idx=0, validate=validate_design)
        meta.add(res["call"])
        if res["valid"]:
            data = res["data"]
            break
        meta.warn(f"раздел 1: попытка {attempt}: {'; '.join(design_problems(res['data']))[:200]}")
        if res["error"]:
            break
    if data is None:
        meta.warn(f"не удалось сгенерировать раздел 1 дизайна за {config.MAX_ATTEMPTS} попытки — запустите генерацию снова")
        data = {f: "" for f in DESIGN_HEADINGS}

    def _v(c):
        return strip_field_header(row[c]) if row.get(c) else ""

    scen_by_seg = {s["segment_id"]: s for s in scenarios}
    offer_by_seg = {o["segment_id"]: o for o in offers}
    design_segments = [{"segment": s,
                        "value_hypotheses": [h for h in hypotheses if h["segment_id"] == s["segment_id"]],
                        "scenario_id": (scen_by_seg.get(s["segment_id"]) or {}).get("scenario_id"),
                        "offer": offer_by_seg.get(s["segment_id"])}
                       for s in segments]
    return {"product_description": {"product_name": _v("product"), "key_function": _v("mechanism"),
                                    "research_goal": _v("decision"), **{f: data[f] for f in DESIGN_HEADINGS}},
            "segments": design_segments, "complete": data["problem_and_losses"] != "", "meta": meta.to_dict()}
