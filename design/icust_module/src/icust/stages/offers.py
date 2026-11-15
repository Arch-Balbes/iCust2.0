"""Этап 4. Поиск респондентов и офферы.

По одному вызову генератора на сегмент, сегменты параллельно; до 3 попыток на сегмент. Пример — экспертный
оффер C0010 из реестра (резерв C0009). Число интервью ставит код по типу сегмента (B2C — «15–20», B2B — «5»).
Фильтр-вопросы копируются из сценария сегмента кодом. Фиксированные каналы — статический блок. Оценщика нет.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .. import config
from ..common import add_interview_block, format_context, product_to_row
from ..knowledge_base import KnowledgeBase, find_leak_case, offer_example_text
from ..llm import Meta, llm_call

INTERVIEW_COUNT = {"B2C": "15–20", "B2B": "5"}      # фиксированно по типу сегмента

FIXED_CHANNELS = {
    "caption": "Общие площадки для поиска респондентов: подходят для любого исследования.",
    "channels": [
        {"title": "Респонденты для рисёча",
         "description": "Чат для объявлений о поиске респондентов. Публиковать бесплатно, но только участникам «ЧАТа рисёчеров».",
         "url": "https://t.me/respondents_for_research"},
        {"title": "ЧАТ рисёчеров",
         "description": "Сообщество исследователей в маркетинге, социологии, продукте, CX и UX. Обсуждают методы, кейсы и инструменты.",
         "url": "https://t.me/researchers_chat"},
        {"title": "Коридорки и кастдев (UNCRN.me)",
         "description": "Чат, где участники договариваются о взаимных кастдев-интервью и коротких созвонах-знакомствах.",
         "url": "https://t.me/+wDZr0lMzCyVmMGUy"},
    ],
}

SYSTEM_PROMPT_OFFER = """Ты — эксперт по CustDev-исследованиям. Для сегмента целевой аудитории ты готовишь план поиска респондентов для проблемных интервью и тексты приглашений.

Заполни поля:
— segment_type: B2B — только если респондент действует от имени компании или организации (рабочая задача, решение принимает компания); команды, сообщества, группы друзей, семьи и частные лица — B2C.
— who_to_find: кого ищем — одним абзацем, как в примере: роль, что делали за последнее время, в каких условиях.
— interview_count_note: только для B2B — почему 5 интервью достаточно и как распределить респондентов (например, по одному из разных компаний); для B2C — пустая строка.
— selection_criteria: признаки отбора — проверяемые условия (роль, частота, недавний опыт задачи и т.п.).
— search_sequence: порядок поиска — сначала самый концентрированный канал, затем остальные; для каждого шага укажи канал и тип оффера.
— channel_recommendations: рекомендации по каналам — площадка и как искать (поисковые запросы, где именно на площадке); тип оффера указывай только в поле offer_type, не в описании. Не называй конкретные чаты, каналы и группы и не давай ссылок на них. В поле url — только корневой домен площадки из списка: {domains}; если площадки нет в списке — пустая строка. Тип оффера: personal, seeding или none, если не важен.
— personal_offer: персональный оффер — личное обращение одному человеку, как в примере.
— seeding_offer: оффер для посева — объявление для публикации в чате или сообществе, как в примере.

Правила:
— Опирайся на описание продукта, гипотезу сегмента, гипотезы ценности и фильтр-вопросы сценария; не добавляй неподтверждённых обстоятельств.
— В приглашениях зови рассказать о своём опыте, а не оценить решение. В благодарность — ранний бесплатный доступ к продукту или его результат для респондента и результаты исследования, как в примере. Не обещай денег и подарков.
— Длительность интервью — 45 минут.
— Пиши на русском языке."""

OFFER_USER_TEMPLATE = ("Пример экспертного плана поиска респондентов и офферов:\n\nОписание продукта:\n{ex_context}\n\n"
                       "{ex_offer}\n\n---\n\n"
                       "Описание продукта:\n{query_context}\n\nСегмент: {segment}\n\nГипотезы ценности для сегмента:\n{hypotheses}\n\n"
                       "Фильтр-вопросы из сценария интервью:\n{screening}")

_OFFER_TYPE = {"type": "string", "enum": ["personal", "seeding"]}
OFFER_SCHEMA = {
    "name": "segment_offer", "strict": True,
    "schema": {"type": "object",
               "properties": {
                   "segment_type": {"type": "string", "enum": ["B2C", "B2B"]},
                   "who_to_find": {"type": "string"},
                   "interview_count_note": {"type": "string"},
                   "selection_criteria": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                   "search_sequence": {"type": "array", "minItems": 1,
                                       "items": {"type": "object",
                                                 "properties": {"channel": {"type": "string"}, "offer_type": _OFFER_TYPE},
                                                 "required": ["channel", "offer_type"], "additionalProperties": False}},
                   "channel_recommendations": {"type": "array", "minItems": 1,
                                               "items": {"type": "object",
                                                         "properties": {"title": {"type": "string"},
                                                                        "description": {"type": "string"},
                                                                        "offer_type": {"type": "string",
                                                                                       "enum": ["personal", "seeding", "none"]},
                                                                        "url": {"type": "string"}},
                                                         "required": ["title", "description", "offer_type", "url"],
                                                         "additionalProperties": False}},
                   "personal_offer": {"type": "string"},
                   "seeding_offer": {"type": "string"}},
               "required": ["segment_type", "who_to_find", "interview_count_note", "selection_criteria",
                            "search_sequence", "channel_recommendations", "personal_offer", "seeding_offer"],
               "additionalProperties": False}}


def screening_questions(scenario: dict) -> list[str]:
    """Фильтр-вопросы из сценария сегмента (строки 4–5), кодом: нумерованные вопросы строки 4 и вопрос строки 5."""
    rows = {it["row_no"]: it["question"] or "" for it in scenario["items"]}
    qs = [re.sub(r"^\d+[.)]\s*", "", l).strip() for l in rows.get(4, "").splitlines() if re.match(r"^\s*\d+[.)]", l)]
    return qs + ([rows[5].strip()] if rows.get(5, "").strip() else [])


def offer_problems(data, allowed_domains: list[str]) -> list[str]:
    if data is None:
        return ["ответ не разобран как JSON"]
    probs = []
    for f in ("who_to_find", "personal_offer", "seeding_offer"):
        if len((data.get(f) or "").strip()) < 20:
            probs.append(f"{f}: пусто или слишком коротко")
    if any(not (s or "").strip() for s in data.get("selection_criteria", [])):
        probs.append("selection_criteria: пустой признак")
    if any(not (s.get("channel") or "").strip() for s in data.get("search_sequence", [])):
        probs.append("search_sequence: пустой канал")
    for r in data.get("channel_recommendations", []):
        if not (r.get("title") or "").strip() or not (r.get("description") or "").strip():
            probs.append("channel_recommendations: пустая площадка или описание")
        if (r.get("url") or "").strip() and r["url"].strip().lower() not in allowed_domains:
            probs.append(f"url {r['url']!r} не из списка разрешённых доменов")
    return probs


def _offer_for_segment(segment, seg_hyps, scenario, query_ctx, example_case, initial_generation, interview_summary,
                       meta, kb: KnowledgeBase):
    screening = screening_questions(scenario) if scenario else []
    user = OFFER_USER_TEMPLATE.format(ex_context=kb.ctx_by_case[example_case], ex_offer=offer_example_text(kb, example_case),
                                      query_context=query_ctx, segment=segment["text"],
                                      hypotheses="\n".join(f"{i}. {h['text']}" for i, h in enumerate(seg_hyps, 1)),
                                      screening="\n".join(screening) or "—")
    user = add_interview_block(user, initial_generation, interview_summary)
    system = SYSTEM_PROMPT_OFFER.replace("{domains}", ", ".join(kb.allowed_domains))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    data = None
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        res = llm_call(config.GEN_MODEL, messages, schema=OFFER_SCHEMA, temperature=config.GEN_TEMPERATURE,
                       sample_idx=0, validate=lambda d: not offer_problems(d, kb.allowed_domains))
        meta.add(res["call"])
        if res["valid"]:
            data = res["data"]
            break
        meta.warn(f"{segment['segment_id']}: попытка {attempt}: "
                  f"{'; '.join(offer_problems(res['data'], kb.allowed_domains))[:200]}")
        if res["error"]:
            break
    if data is None:
        meta.warn(f"{segment['segment_id']}: не удалось сгенерировать оффер за {config.MAX_ATTEMPTS} попытки — "
                  "запустите генерацию снова")
        data = {"segment_type": None, "who_to_find": "", "interview_count_note": None, "selection_criteria": [],
                "search_sequence": [], "channel_recommendations": [], "personal_offer": "", "seeding_offer": ""}
    return {"segment_id": segment["segment_id"],
            "who_to_find": data["who_to_find"],
            "interview_count": INTERVIEW_COUNT.get(data["segment_type"]),
            "interview_count_note": (data["interview_count_note"] or "").strip() or None,   # пустая строка -> null
            "selection_criteria": data["selection_criteria"],
            "screening_questions": screening,
            "search_sequence": [{"step_no": i, **s} for i, s in enumerate(data["search_sequence"], 1)],
            "channel_recommendations": [{"title": r["title"], "description": r["description"],
                                         "offer_type": None if r["offer_type"] == "none" else r["offer_type"],
                                         "url": (r["url"] or "").strip().lower() or None}
                                        for r in data["channel_recommendations"]],
            "personal_offer": data["personal_offer"],
            "seeding_offer": data["seeding_offer"]}, data["segment_type"] is not None


def generate_offers(product: dict, segments: list[dict], hypotheses: list[dict], scenarios: list[dict],
                    kb: KnowledgeBase, initial_generation: bool = True, interview_summary: dict | None = None) -> dict:
    """Этап 4. Ответ по контракту OfferResponse."""
    row = product_to_row(product)
    query_ctx = format_context(row)
    example_case = config.pick_example(config.OFFER_EXAMPLE, find_leak_case(row, kb))
    scen_by_seg = {s["segment_id"]: s for s in scenarios}
    metas = [Meta() for _ in segments]
    with ThreadPoolExecutor(max_workers=max(1, len(segments))) as ex:
        futs = [ex.submit(_offer_for_segment, s, [h for h in hypotheses if h["segment_id"] == s["segment_id"]],
                          scen_by_seg.get(s["segment_id"]), query_ctx, example_case,
                          initial_generation, interview_summary, m, kb)
                for s, m in zip(segments, metas)]
        results = [f.result() for f in futs]
    meta = Meta()
    for m in metas:
        meta.merge(m)
    return {"offers": [o for o, _ in results], "fixed_channels": FIXED_CHANNELS,
            "complete": all(ok for _, ok in results), "meta": meta.to_dict()}
