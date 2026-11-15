"""Этап 3. Сценарий интервью по шаблону SCORE/JTBD.

Модель возвращает только вставки в `<…>` по строкам шаблона (строки 4 и 40 — целиком, одной вставкой);
текст шаблона вокруг вставок подставляет код, поэтому исказить его модель не может. Вставки в ответе —
в угловых скобках, как в эталонных сценариях. Проверка: все строки на месте, число вставок совпадает
с шаблоном. Пример — вставки эксперта из первого сегмента C0008 (резерв C0006). Оценщика нет.
По одному вызову на сегмент, сегменты параллельно; до 3 попыток на сегмент.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from .. import config
from ..common import add_interview_block, format_context, product_to_row
from ..knowledge_base import GENERATED_ROWS, TEMPLATE_NOTE, KnowledgeBase, find_leak_case
from ..llm import Meta, llm_call

SYSTEM_PROMPT_SCEN = """Ты — эксперт по CustDev-исследованиям. Ты адаптируешь шаблон сценария проблемного интервью (SCORE/JTBD) под конкретный сегмент целевой аудитории.

Текст шаблона не переписывай: верни только вставки — что подставить вместо каждого фрагмента в угловых скобках.

Правила:
— В строках шаблона фрагменты для замены пронумерованы: <1: …>, <2: …>. Для каждой строки верни список вставок в том же порядке и в том же количестве, без угловых скобок. Вставка должна грамматически продолжать текст шаблона вокруг неё.
— Если фрагмент — подсказка интервьюеру (например, «подставить из ответа»), оставь её подсказкой, как в примере.
— Пометки с метками полей в круглых скобках, например «(гипотеза работы {Б1})», — подсказки, что подставить.
— Строку 4 (фильтр-вопросы по сегменту) и строку 40 (описательные вопросы по портрету потребителя) напиши целиком, одной вставкой: нумерованные вопросы, по которым можно отобрать представителей сегмента и описать их портрет, — как в примере.
— Верни все строки из блока «Строки шаблона для адаптации», ни одной не пропускай.
— Опирайся на описание продукта, гипотезу сегмента и гипотезы ценности; не добавляй неподтверждённых обстоятельств.
— Не описывай в вопросах продукт и его функции.
— Пиши на русском языке."""

SCEN_USER_TEMPLATE = ("Пример адаптации шаблона экспертом (вставки по строкам):\n\nОписание продукта:\n{ex_context}\n\nСегмент: {ex_segment}\n\n"
                      "{ex_rows}\n\n---\n\n"
                      "Описание продукта:\n{query_context}\n\nСегмент: {segment}\n\nГипотезы ценности для сегмента:\n{hypotheses}\n\n"
                      "Строки шаблона для адаптации:\n{rows}")


def slot_fills(text) -> list[str]:
    """Вставки из готовой строки сценария: фрагменты в <…> по порядку."""
    return [f.strip() for f in re.findall(r"<([^>]*)>", text or "")]


def _template(kb: KnowledgeBase) -> SimpleNamespace:
    """Шаблон: тексты строк, число вставок по строкам, блок строк для промпта (один раз на базу)."""
    if "scenarios" in kb.cache:
        return kb.cache["scenarios"]
    tpl, rows_to_fill = kb.scen_template, kb.rows_to_fill
    questions = dict(zip(tpl["row_no"], tpl["question"]))
    n_slots = {n: (1 if n in GENERATED_ROWS else len(re.findall(r"<[^>]*>", questions[n]))) for n in rows_to_fill}
    parts = []
    for r in tpl[tpl["row_no"].isin(rows_to_fill)].itertuples():
        head = f"Строка {r.row_no} [{r.section}{' / ' + r.topic if isinstance(r.topic, str) else ''}]"
        if r.row_no in GENERATED_ROWS:
            parts.append(f"{head} — написать целиком, 1 вставка:\n{r.question}")
        else:
            k = iter(range(1, 100))
            q = re.sub(r"<([^>]*)>", lambda m: f"<{next(k)}: {m.group(1)}>", r.question)
            parts.append(f"{head} — вставок: {n_slots[r.row_no]}:\n{q}")
    t = SimpleNamespace(questions=questions, n_slots=n_slots, rows_to_fill=rows_to_fill, rows_block="\n\n".join(parts))
    kb.cache["scenarios"] = t
    return t


def format_scenario_example(case_id: str, kb: KnowledgeBase) -> tuple[str, str, str]:
    """Первый сегмент эталонного кейса: вставки эксперта по строкам (строки 4 и 40 — целиком)."""
    t = _template(kb)
    seg_id, rows = next(iter(kb.scen_examples[case_id].items()))
    rows = rows.set_index("row_no")
    lines = []
    for n in t.rows_to_fill:
        q = rows.loc[n, "question"]
        if n in GENERATED_ROWS:
            lines.append(f"Строка {n}:\n1) {q}")
        else:
            lines.append(f"Строка {n}:\n" + "\n".join(f"{i}) {f}" for i, f in enumerate(slot_fills(q), 1)))
    seg_text = kb.seg_base.set_index("segment_id").loc[seg_id, "text"]
    return kb.ctx_by_case[case_id], seg_text, "\n\n".join(lines)


def scenario_schema(t: SimpleNamespace) -> dict:
    n = len(t.rows_to_fill)
    return {"name": "scenario_rows", "strict": True,
            "schema": {"type": "object",
                       "properties": {"rows": {"type": "array", "minItems": n, "maxItems": n,
                                               "items": {"type": "object",
                                                         "properties": {"row_no": {"type": "integer"},
                                                                        "fills": {"type": "array", "items": {"type": "string"}}},
                                                         "required": ["row_no", "fills"],
                                                         "additionalProperties": False}}},
                       "required": ["rows"], "additionalProperties": False}}


def scenario_rows(data) -> dict[int, list[str]]:
    """Ответ модели -> {номер строки: список вставок}."""
    return {r.get("row_no"): r.get("fills") or [] for r in (data or {}).get("rows", [])}


def scenario_problems(data, t: SimpleNamespace) -> list[str]:
    if data is None:
        return ["ответ не разобран как JSON"]
    got = scenario_rows(data)
    probs = []
    missing = [n for n in t.rows_to_fill if n not in got]
    if missing:
        probs.append(f"нет строк {missing}")
    for n, fills in got.items():
        if n not in t.n_slots:
            continue
        if len(fills) != t.n_slots[n]:
            probs.append(f"строка {n}: вставок {len(fills)} вместо {t.n_slots[n]}")
        elif any(len(f.strip(" <>")) < (20 if n in GENERATED_ROWS else 2) for f in fills):
            probs.append(f"строка {n}: пустая вставка")
    return probs


def assemble_row(row_no: int, fills: list[str], t: SimpleNamespace) -> str:
    """Строка сценария: текст шаблона кодом, вставки модели — в <…> (строки 4 и 40 — целиком)."""
    if row_no in GENERATED_ROWS:
        return fills[0].strip()
    it = iter(fills)
    q = re.sub(r"<[^>]*>", lambda m: f"<{next(it).strip(' <>')}>", t.questions[row_no])
    return TEMPLATE_NOTE.sub(" ", q)


def _str_or_none(v):
    return v if isinstance(v, str) else None   # NaN из таблицы -> None (валидный JSON)


def _scenario_for_segment(segment, seg_hyps, query_ctx, example_case, initial_generation, interview_summary,
                          meta, kb: KnowledgeBase):
    t = _template(kb)
    ex_ctx, ex_seg, ex_rows = format_scenario_example(example_case, kb)
    user = SCEN_USER_TEMPLATE.format(ex_context=ex_ctx, ex_segment=ex_seg, ex_rows=ex_rows, query_context=query_ctx,
                                     segment=segment["text"],
                                     hypotheses="\n".join(f"{i}. {h['text']}" for i, h in enumerate(seg_hyps, 1)),
                                     rows=t.rows_block)
    user = add_interview_block(user, initial_generation, interview_summary)
    messages = [{"role": "system", "content": SYSTEM_PROMPT_SCEN}, {"role": "user", "content": user}]
    filled = None
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        res = llm_call(config.GEN_MODEL, messages, schema=scenario_schema(t), temperature=config.GEN_TEMPERATURE,
                       sample_idx=0, validate=lambda d: not scenario_problems(d, t))
        meta.add(res["call"])
        if res["valid"]:
            filled = scenario_rows(res["data"])
            break
        meta.warn(f"{segment['segment_id']}: попытка {attempt}: {'; '.join(scenario_problems(res['data'], t))[:200]}")
        if res["error"]:
            break
    items = []
    for r in kb.scen_template.itertuples():
        if filled and r.row_no in filled:
            q = assemble_row(r.row_no, filled[r.row_no], t)
        else:
            q = TEMPLATE_NOTE.sub(" ", r.question or "")
        items.append({"row_no": r.row_no, "section": _str_or_none(r.section), "topic": _str_or_none(r.topic),
                      "question": re.sub(r"[ \t]+", " ", q).strip(), "hint": _str_or_none(r.hint)})
    if filled is None:
        meta.warn(f"{segment['segment_id']}: не удалось сгенерировать сценарий за {config.MAX_ATTEMPTS} попытки — "
                  "запустите генерацию снова")
    return {"scenario_id": f"{segment['segment_id']}-SC", "segment_id": segment["segment_id"],
            "title": (segment.get("elements") or {}).get("role") or segment["segment_id"],
            "items": items}, filled is not None


def generate_scenarios(product: dict, segments: list[dict], hypotheses: list[dict], kb: KnowledgeBase,
                       initial_generation: bool = True, interview_summary: dict | None = None) -> dict:
    """Этап 3. Ответ по контракту ScenarioResponse."""
    _template(kb)                                                  # собрать шаблон до запуска потоков
    row = product_to_row(product)
    query_ctx = format_context(row)
    example_case = config.pick_example(config.SCENARIO_EXAMPLE, find_leak_case(row, kb))
    metas = [Meta() for _ in segments]
    with ThreadPoolExecutor(max_workers=max(1, len(segments))) as ex:
        futs = [ex.submit(_scenario_for_segment, s, [h for h in hypotheses if h["segment_id"] == s["segment_id"]],
                          query_ctx, example_case, initial_generation, interview_summary, m, kb)
                for s, m in zip(segments, metas)]
        results = [f.result() for f in futs]
    meta = Meta()
    for m in metas:
        meta.merge(m)
    return {"scenarios": [s for s, _ in results], "complete": all(ok for _, ok in results), "meta": meta.to_dict()}
