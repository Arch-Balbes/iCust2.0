"""ИГ3 — инсайты (определение 06.11.2026, конвейер 14.11.2026; перенос scripts/ig3_model_compare_2026_11_14.py
вариант glm_mr и scripts/ig3_merge_2026_11_14.py).

По каждому сегменту отдельно (слияния между сегментами нет — у каждого сегмента своя гипотеза):
  map    — пачки по 4 респондента: утверждения ИГ1 → наблюдения-расхождения с гипотезой (GLM без рассуждения);
  reduce — наблюдения сегмента → инсайты по методике (method.txt);
  merge  — слияние дублей и отсев пересказов компонентов (reasoning_effort=low; при обрыве — без рассуждения);
  check  — каждый инсайт сверяется со ВСЕМИ утверждениями сегмента пачками по 4 респондента;
  код    — считает поддерживающих / контрпримеры, уровень (stable от 3 респондентов), критерий подтверждаемости,
           подставляет цитаты дословно из source_quote и таймкоды реплик.
Инсайты, добавленные пользователем (source=user), пересчёт не трогает.
"""
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.ig1.domains import CONTEXT_LABELS
from app.ig1.llm import LOW_REASONING, Llm, LlmError
from app.ig1.pipeline import _llm, _statement
from app.models import Claim, Component, Hypothesis, Insight, Interview, Project, Turn

BATCH = 4
STABLE_MIN = 3
METHOD = (Path(__file__).parent / "method.txt").read_text(encoding="utf-8")
SYSTEM = ("Ты опытный исследователь custdev. Отвечаешь на русском. "
          "Возвращаешь только один JSON-объект без пояснений и без markdown-обёртки.")

MAP_TASK = """# Задание (шаг map)

Перед тобой утверждения нескольких респондентов одного сегмента. Найди в них **наблюдения-расхождения** с гипотезой:
где то, что говорят люди, уточняет, опровергает или дополняет предположение гипотезы по конкретному слоту
(Б роль, Б1 задача, Б2 ситуация, В проблема, В1 потери, Г решение, Д результат, Е альтернативы), и почему люди поступают так.
Ищи: как на самом деле решают задачу и что используют; реальный механизм проблемы; реальную единицу потерь;
кто принимает решение; почему держатся за текущие альтернативы; неожиданные подгруппы. Чистое подтверждение компонента
без нового — не наблюдение. Опирайся только на эти утверждения, ничего не выдумывай.

Верни JSON:
{"observations": [{"hypothesis": "<код гипотезы сегмента или ценности>", "element": "<например Проблема {В}>",
 "slots": ["В"], "relation": "Дополняет | Опровергает | Подтверждает и дополняет",
 "expected": "что предполагала гипотеза", "observed": "что говорят эти респонденты",
 "explanation": "почему так (если видно из данных)",
 "respondent_ids": ["..."], "claim_ids": ["..."], "counter_respondent_ids": ["..."]}]}
claim_ids — только из списка выше, не больше 8 самых показательных на наблюдение; respondent_ids — авторы этих
утверждений. expected и observed — своими словами, коротко (до 300 знаков), не переписывай утверждения подряд.
Обычно 3–10 наблюдений на пачку. Если расхождений нет — {"observations": []}.
"""

REDUCE_TASK = """# Задание (шаг reduce)

Выше — наблюдения-расхождения, собранные по пачкам респондентов сегмента {seg} (всего респондентов в сегменте: {n_seg}).
Одно и то же расхождение могло прийти из разных пачек — объединяй их, складывая респондентов (один человек считается один раз).
Сформулируй из наблюдений инсайты по методике: объедини похожие, отбрось то, что лишь повторяет компонент гипотезы,
оцени четыре критерия честно (1–2 респондента — подтверждаемость «Нет»).

Верни JSON {"insights": [...]} по формату инсайта из методики, с уточнениями:
- в evidence укажи только claim_id и respondent_id (3–8 штук из claim_ids наблюдений), поле quote не пиши — его подставит код;
- другие сегменты не упоминай. Если инсайтов нет — {"insights": []}.
"""

MERGE_TASK = """# Задание (шаг слияния)

Ниже — инсайты одного сегмента {SEG}, полученные по частям. Среди них есть дубли и пересечения. Все инсайты относятся
к гипотезе этого сегмента; другие сегменты не рассматривай и не упоминай.

1. Разбей ВСЕ входные инсайты на группы: в группу — инсайты с одной сутью расхождения «гипотеза предполагала X →
   по данным Y» по тем же или пересекающимся слотам. Каждый входной id должен попасть ровно в одну группу.
2. Для каждой группы реши keep: false, если это по сути повтор компонента гипотезы или чистое подтверждение без нового,
   тема без вывода, либо вывод противоречит другим, более сильным группам. Иначе keep: true.
3. Для keep: true напиши итоговый инсайт по методике: самую точную формулировку с механизмом «почему».
   НЕ пиши в текстах чисел респондентов и долей («N из M», «большинство») — их посчитает код по корпусу.
   criterion — проверяемый критерий включения: какое высказывание респондента считается подтверждением
   этого инсайта (1–2 предложения), чтобы по нему можно было разметить каждое утверждение.
   title — короткий заголовок карточки (до 100 знаков).

Верни JSON:
{"groups": [{"members": ["<id>", ...], "keep": true, "drop_reason": null,
  "hypothesis": "<код гипотезы сегмента или ценности>", "element": "Проблема {В}", "affected_slots": ["В"],
  "affected_component_ids": [], "relation_expert": "Дополняет | Опровергает | Подтверждает и дополняет",
  "relation_to_hypothesis": "refines | contradicts | extends | outside",
  "type": "new_solution | new_usage | different_job | different_condition | contradiction_mechanism | slot_refinement",
  "title": "...", "insight": "...", "expected": "...", "observed": "...", "explanation": "...", "criterion": "...",
  "analytic": {"text": "...", "passed": true}, "significance": {"text": "...", "passed": true},
  "proportionality": {"text": "...", "passed": true},
  "boundaries": ["..."], "suggested_actions": [{"kind": "...", "component_id": null, "text": "..."}]}]}
"""

CHECK_TASK = """# Задание (проверка инсайтов по утверждениям)

Для каждого инсайта из списка выше и каждого утверждения из списка выше реши, как утверждение относится к критерию
инсайта: supports — утверждение респондента прямо подтверждает критерий (его личный опыт или позиция);
contradicts — прямо противоречит ему; иначе — не относится (такие пары не выводи).
Гипотетические ответы («было бы удобно», «наверное») считаются только если критерий сам про ожидания.

Верни JSON: {"links": [{"insight_id": "...", "claim_id": "...", "role": "supports | contradicts"}]}
Только claim_id из списка утверждений этой пачки. Если связей нет — {"links": []}.
"""


def batches(ids: list[str], size: int = BATCH) -> list[list[str]]:
    n = len(ids)
    if n == 0:
        return []
    k = max(1, round(n / size))
    step = n / k
    return [ids[round(i * step):round((i + 1) * step)] for i in range(k)]


def claim_line(c: dict[str, Any]) -> str:
    return json.dumps({k: c[k] for k in ("claim_id", "respondent_id", "segment", "claim_text", "source_quote")},
                      ensure_ascii=False)


def context_md(ctx: dict[str, Any], hyps: list[Hypothesis], comps: list[Component], resp: list[str]) -> str:
    lines = ["## Анкета (исходное видение команды, слоты А–Ж)", ""]
    lines += [f"{label}: {ctx.get(key, '')}" for key, label in CONTEXT_LABELS.items() if ctx.get(key)]
    lines += ["", "## Гипотезы сегмента", ""]
    for h in hyps:
        kind = "гипотеза сегмента" if h.kind == "segment" else "гипотеза ценности"
        lines.append(f"- {h.code} ({kind}): " + " ".join(_statement(x) for x in h.lines))
    lines += ["", "## Компоненты гипотез", ""]
    lines += [f"- {c.component_id}: {c.statement}" for c in comps]
    lines += ["", f"## Респонденты сегмента: {', '.join(resp)}"]
    return "\n".join(lines)


async def _merge(llm: Llm, user: str) -> dict[str, Any]:
    try:
        return await llm.call("ig3_merge", SYSTEM, user, thinking=True, extra=LOW_REASONING)
    except LlmError:  # 14.11.2026: рассуждение даже при effort=low съедало весь лимит — повтор без рассуждения
        return await llm.call("ig3_merge", SYSTEM, user)


async def _load(project_id: str, segment: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    async with SessionLocal() as s:
        project = await s.get(Project, project_id)
        hyps = list((await s.scalars(select(Hypothesis).where(Hypothesis.project_id == project_id,
                                                              Hypothesis.segment_code == segment,
                                                              Hypothesis.selected))).all())
        comps = list((await s.scalars(select(Component).where(
            Component.hypothesis_id.in_([h.id for h in hyps] or [-1])))).all())
        rows = (await s.execute(
            select(Claim, Interview).join(Interview, Claim.interview_id == Interview.id)
            .where(Interview.project_id == project_id, Interview.segment_code == segment,
                   Interview.status == "processed").order_by(Interview.id, Claim.turn_index))).all()
        iv_ids = list({iv.id for _, iv in rows}) or [-1]
        turn_time = {(t.interview_id, t.turn_index): t.start_sec
                     for t in (await s.scalars(select(Turn).where(Turn.interview_id.in_(iv_ids)))).all()}
    claims = [dict(claim_id=c.claim_id, respondent_id=iv.respondent_code, segment=segment, claim_text=c.claim_text,
                   source_quote=c.source_quote, time=turn_time.get((iv.id, c.turn_index), 0.0)) for c, iv in rows]
    resp = sorted({c["respondent_id"] for c in claims})
    return context_md(project.context if project else {}, hyps, comps, resp), claims, resp


async def run_segment(project_id: str, segment: str) -> dict[str, Any]:
    ctx, claims, ids = await _load(project_id, segment)
    by_claim = {c["claim_id"]: c for c in claims}
    llm = _llm(project_id)
    try:
        # map
        observations: list[dict[str, Any]] = []
        for b in batches(ids):
            bc = [c for c in claims if c["respondent_id"] in b]
            user = (f"# Вход проекта\n\n{ctx}\n\n# Утверждения респондентов {', '.join(b)} (сегмент {segment})\n\n"
                    + "\n".join(claim_line(c) for c in bc) + "\n\n" + MAP_TASK)
            obj = await llm.call("ig3_map", SYSTEM, user)
            valid = {c["claim_id"] for c in bc}
            for o in obj.get("observations") or []:
                o["claim_ids"] = [x for x in o.get("claim_ids", []) if x in valid]
                o["respondent_ids"] = sorted({by_claim[x]["respondent_id"] for x in o["claim_ids"]}
                                             | {r for r in o.get("respondent_ids", []) if r in b})
                observations.append(o)
        if not observations:
            return await _save(project_id, segment, [], 0)
        # reduce
        user = (f"# Методика\n\n{METHOD}\n\n# Вход проекта\n\n{ctx}\n\n# Наблюдения сегмента {segment} "
                f"({len(observations)} шт.)\n\n" + "\n".join(json.dumps(o, ensure_ascii=False) for o in observations)
                + "\n\n" + REDUCE_TASK.replace("{seg}", segment).replace("{n_seg}", str(len(ids))))
        reduced = (await llm.call("ig3_reduce", SYSTEM, user)).get("insights") or []
        for i, ins in enumerate(reduced, 1):
            ins["insight_id"] = f"{segment}-R-{i:02d}"  # id задаёт код: слиянию нужны уникальные
        if not reduced:
            return await _save(project_id, segment, [], len(observations))
        # merge
        keys = ["insight_id", "hypothesis", "element", "affected_slots", "affected_component_ids",
                "relation_expert", "insight", "expected", "observed", "explanation"]
        inp = [{k: x.get(k) for k in keys} for x in reduced]
        user = (f"# Методика\n\n{METHOD}\n\n# Вход проекта\n\n{ctx}\n\n# Инсайты сегмента {segment}, полученные по "
                f"частям ({len(inp)} шт.)\n\n" + "\n".join(json.dumps(x, ensure_ascii=False) for x in inp)
                + "\n\n" + MERGE_TASK.replace("{SEG}", segment))
        groups = [g for g in (await _merge(llm, user)).get("groups") or [] if g.get("keep")]
        for n, g in enumerate(groups, 1):
            g["insight_id"] = f"{segment}-INS-{n:02d}"
        # check по всем утверждениям сегмента
        links: list[dict[str, Any]] = []
        ins_lines = "\n".join(json.dumps({k: g.get(k) for k in ("insight_id", "insight", "criterion", "expected",
                                                                 "observed")}, ensure_ascii=False) for g in groups)
        for b in batches(ids) if groups else []:
            bc = [c for c in claims if c["respondent_id"] in b]
            user = (f"# Инсайты ({len(groups)} шт.)\n\n{ins_lines}\n\n# Утверждения респондентов {', '.join(b)}\n\n"
                    + "\n".join(claim_line(c) for c in bc) + "\n\n" + CHECK_TASK)
            obj = await llm.call("ig3_check", SYSTEM, user)
            valid_c, valid_i = {c["claim_id"] for c in bc}, {g["insight_id"] for g in groups}
            links += [x for x in obj.get("links") or [] if x.get("claim_id") in valid_c
                      and x.get("insight_id") in valid_i and x.get("role") in ("supports", "contradicts")]
    finally:
        await llm.aclose()
    return await _save(project_id, segment, [score(g, links, by_claim, len(ids)) for g in groups], len(observations))


def score(g: dict[str, Any], links: list[dict[str, Any]], by_claim: dict[str, dict[str, Any]], n_seg: int) -> dict[str, Any]:
    """Пересчёт кодом: опора, контрпримеры, уровень, подтверждаемость, цитаты дословно из source_quote."""
    sup_map: dict[str, list[str]] = defaultdict(list)
    con_map: dict[str, list[str]] = defaultdict(list)
    for x in links:
        if x["insight_id"] == g["insight_id"]:
            rid = by_claim[x["claim_id"]]["respondent_id"]
            (sup_map if x["role"] == "supports" else con_map)[rid].append(x["claim_id"])
    both = set(sup_map) & set(con_map)  # смешанный респондент: решает число его утверждений
    sup = sorted(r for r in sup_map if r not in both or len(sup_map[r]) >= len(con_map[r]))
    con = sorted(r for r in con_map if r not in sup)
    counts = f"{len(sup)} из {n_seg}" + (f", против {len(con)}" if con else "")
    empirical = {"text": f"Поддерживают по корпусу: {counts} (подсчёт кодом по утверждениям).",
                 "passed": len(sup) >= STABLE_MIN}
    crit = {"analytic": g.get("analytic") or {}, "empirical": empirical,
            "significance": g.get("significance") or {}, "proportionality": g.get("proportionality") or {}}
    ev = []
    for r in sorted(sup, key=lambda r: -max(len(by_claim[c]["source_quote"]) for c in sup_map[r]))[:6]:
        cid = max(sup_map[r], key=lambda c: len(by_claim[c]["source_quote"]))
        ev.append({"respondent_id": r, "claim_id": cid, "role": "supports", "quote": by_claim[cid]["source_quote"],
                   "time": by_claim[cid]["time"]})
    for r in con[:2]:
        cid = con_map[r][0]
        ev.append({"respondent_id": r, "claim_id": cid, "role": "counterexample", "quote": by_claim[cid]["source_quote"],
                   "time": by_claim[cid]["time"]})
    out = {k: g.get(k) for k in ("insight_id", "hypothesis", "element", "affected_slots", "affected_component_ids",
                                 "relation_expert", "relation_to_hypothesis", "type", "title", "insight", "expected",
                                 "explanation", "criterion", "boundaries", "suggested_actions")}
    out.update(observed=f"{g.get('observed') or ''} ({counts})", evidence=ev, criteria=crit,
               respondents={"supporting": sup, "counterexamples": con, "n_supporting": len(sup), "n_segment": n_seg},
               accepted=all(crit[k].get("passed") is True for k in crit),
               level="stable" if len(sup) >= STABLE_MIN else "candidate")
    return out


async def _save(project_id: str, segment: str, insights: list[dict[str, Any]], n_obs: int) -> dict[str, Any]:
    async with SessionLocal() as s:
        await s.execute(delete(Insight).where(Insight.project_id == project_id, Insight.segment_code == segment,
                                              Insight.source == "llm"))
        for ins in insights:
            s.add(Insight(project_id=project_id, segment_code=segment, insight_code=ins["insight_id"], source="llm",
                          level=ins["level"], accepted=ins["accepted"], data=ins, comments=[]))
        await s.commit()
    return {"segment": segment, "observations": n_obs, "insights": len(insights),
            "stable": sum(i["level"] == "stable" for i in insights)}


async def run_project(project_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as s:
        segments = sorted(set((await s.scalars(select(Interview.segment_code).where(
            Interview.project_id == project_id, Interview.status == "processed"))).all()))
    return [await run_segment(project_id, seg) for seg in segments]
