"""Сборка результатов для экранов 11–12 и выгрузок: валидация (ИГ2) по слотам с цитатами и таймкодами,
сводка анализа для повторной генерации у коллеги (interview_summary), пакет результатов (RESULTS_PACKAGE_SPEC.md),
документы .md/.docx (дизайн, сценарий, отчёт). Правила ИГ2 — только из app.ig1.ig2.
"""
import io
import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.design import service as design
from app.ig1 import ig2
from app.models import Claim, Component, DesignStage, Hypothesis, Insight, Interview, Pair, PlanQuestion, Project, Turn

SLOT_LABEL = {"product": "Продукт", "role": "Роль", "situation": "Ситуация", "job": "Задача", "outcome": "Результат",
              "problem": "Проблема", "losses": "Потери", "function": "Функция", "effect": "Эффект"}
STATUS_LABEL = {"confirmed": "Подтверждено", "refuted": "Опровергнуто", "ambiguous": "Неоднозначно",
                "insufficient": "Мало данных", "not_tested": "Не проверялось"}
KIND_TITLE = {"segment": "Гипотеза потребительского сегмента", "value": "Гипотеза ценности продукта"}


def mmss(sec: float | None) -> str:
    if sec is None:
        return ""
    s = int(sec)
    return f"{s // 60:02d}:{s % 60:02d}"


async def question_slots(project_id: str) -> dict[str, dict[str, list[str]]]:
    """«Проверяет: …» у вопроса сценария — слоты компонентов, связанных с вопросом на шаге 3а."""
    async with SessionLocal() as s:
        comps = (await s.execute(select(Component.component_id, Component.slot).join(Hypothesis)
                                 .where(Hypothesis.project_id == project_id))).tuples().all()
        slot_of = dict(comps)
        out: dict[str, dict[str, list[str]]] = defaultdict(dict)
        for q in (await s.scalars(select(PlanQuestion).where(PlanQuestion.project_id == project_id))).all():
            slots = list(dict.fromkeys(slot_of[c] for c in q.component_ids if c in slot_of))
            if slots:
                out[q.segment_code][q.question_id] = slots
        return out


def ui_status(r: ig2.ComponentResult) -> str:
    if r.status == "insufficient" and r.k > 0 and r.c > 0:
        return "ambiguous"  # below_threshold: есть и «за», и «против»
    return r.status


async def validation(project_id: str) -> list[dict[str, Any]]:
    """ИГ2 по каждой выбранной гипотезе: строка на атомарный компонент (слот + текст), статус, k/c, цитаты."""
    async with SessionLocal() as s:
        hyps = (await s.scalars(select(Hypothesis).where(Hypothesis.project_id == project_id, Hypothesis.selected)
                                .order_by(Hypothesis.segment_code, Hypothesis.kind))).all()  # segment, затем value
        out = []
        for h in hyps:
            ivs = (await s.scalars(select(Interview).where(Interview.project_id == project_id,
                                                           Interview.segment_code == h.segment_code,
                                                           Interview.status == "processed"))).all()
            respondents = [i.respondent_code for i in ivs]
            comps = (await s.scalars(select(Component).where(Component.hypothesis_id == h.id).order_by(Component.id))).all()
            lead_of = {ln["slot"]: ln.get("lead") for ln in h.lines}
            rows = []
            for comp in comps:
                q = (select(Pair, Claim, Interview, Turn.start_sec).join(Claim, Pair.claim_pk == Claim.id)
                     .join(Interview, Claim.interview_id == Interview.id)
                     .outerjoin(Turn, (Turn.interview_id == Interview.id) & (Turn.turn_index == Claim.turn_index))
                     .where(Pair.component_pk == comp.id, Interview.status == "processed"))
                by_resp: dict[str, list[ig2.Evidence]] = defaultdict(list)
                time_of: dict[str, float | None] = {}
                for pair, claim, iv, start in (await s.execute(q)).tuples().all():
                    by_resp[iv.respondent_code].append(ig2.Evidence(
                        respondent=iv.respondent_code, label=pair.label, subject=claim.subject,
                        turn_index=claim.turn_index, claim_id=claim.claim_id, quote=claim.source_quote))
                    time_of[claim.claim_id] = start
                r = ig2.component_status(by_resp, respondents, comp.quantifier)

                def quotes(verdicts: tuple[str, ...], label: str, by: dict[str, list[ig2.Evidence]] = by_resp,
                           res: ig2.ComponentResult = r, times: dict[str, float | None] = time_of) -> list[dict[str, str]]:
                    qs = []
                    for resp, (v, _w) in res.verdicts.items():
                        if v in verdicts:
                            ev = [e for e in by[resp] if e.label == label]
                            if ev:
                                e = ev[-1]
                                qs.append(dict(respondentId=resp, time=mmss(times.get(e.claim_id)), text=e.quote))
                    return qs[:6]
                lead = lead_of.get(comp.slot)
                if lead and comp.statement.lower().startswith(lead.lower()):
                    lead = None  # шаг 0 уже включил связку в формулировку компонента
                rows.append(dict(
                    slot=comp.slot, componentId=comp.component_id, text=comp.statement, lead=lead,
                    status=ui_status(r), k=r.k, c=r.c, riOnly=r.ri_only, mixed=r.mixed,
                    thirdPartyOnly=r.third_party_only, quantifier=comp.quantifier,
                    pilot=comp.verification_method != "interview",
                    supporting=quotes(("supports", "mixed"), "S"), contradicting=quotes(("contradicts", "mixed"), "C")))
            status, percent = ig2.hypothesis_percent([str(x["status"]) for x in rows], len(respondents))
            out.append(dict(segmentId=h.segment_code, kind=h.kind, hypothesisId=h.code, nInterviews=len(respondents),
                            lines=h.lines, status=status, percent=percent, components=rows))
        return out


def _overlap(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"\w{4,}", a.lower())), set(re.findall(r"\w{4,}", b.lower()))
    return len(wa & wb) / max(1, len(wa | wb))


def reformulated(st: dict[str, dict[str, Any]], selection: dict[str, Any]) -> dict[str, Any]:
    """Актуальные гипотезы после «Переформулировать» (11.2) и изменения по слотам (отчёт, раздел А3)."""
    ref = st.get("reformulate")
    if not ref:
        return {}
    old_segs, old_hyps = design.selected(st.get("segments", {}), st.get("hypotheses", {}), selection)
    new_segs = ref["segments"].get("segments", [])
    new_hyps = ref["hypotheses"].get("hypotheses", [])
    out: dict[str, Any] = {}
    for old in old_segs:
        if not new_segs:
            break
        new = max(new_segs, key=lambda x: _overlap(x["text"], old["text"]))  # ближайший по смыслу новый сегмент
        own = [h for h in new_hyps if h["segment_id"] == new["segment_id"]]
        new_v = next((h for h in own if (h.get("check") or {}).get("passed")), own[0] if own else None)
        old_v = next((h for h in old_hyps if h["segment_id"] == old["segment_id"]), None)
        seg_lines = design.slot_lines(new.get("elements"), new["text"], "segment")
        val_lines = design.slot_lines(new_v.get("elements"), new_v["text"], "value") if new_v else []
        changes = []
        for kind, before, after in (("segment", design.slot_lines(old.get("elements"), old["text"], "segment"), seg_lines),
                                    ("value", design.slot_lines(old_v.get("elements"), old_v["text"], "value")
                                     if old_v else [], val_lines)):
            b = {x["slot"]: x["text"] for x in before}
            for x in after:
                if b.get(x["slot"]) and b[x["slot"]].strip() != x["text"].strip():
                    changes.append(dict(kind=kind, slot=x["slot"], before=b[x["slot"]], after=x["text"]))
        out[old["segment_id"]] = dict(segment=seg_lines, value=val_lines, changes=changes)
    return out


async def interview_summary(project_id: str) -> dict[str, str]:
    """Сводка анализа для повторной генерации у коллеги (CONTRACT.md: dict «поле: значение»)."""
    val = await validation(project_id)
    async with SessionLocal() as s:
        ins = (await s.scalars(select(Insight).where(Insight.project_id == project_id))).all()
    out: dict[str, str] = {}
    for v in val:
        parts = [f"{SLOT_LABEL.get(c['slot'], c['slot'])} «{c['text']}» — {STATUS_LABEL[c['status']]} "
                 f"({c['k']:g} за, {c['c']:g} против)" for c in v["components"]]
        pct = f"{v['percent']:g} %" if v["percent"] is not None else "нет данных"
        out[f"{v['segmentId']} {KIND_TITLE[v['kind']].lower()}: проверка по {v['nInterviews']} интервью, {pct}"] = \
            "; ".join(parts)
    for seg in sorted({i.segment_code for i in ins}):
        lines = [f"{i.data.get('title') or i.data.get('insight')}: в гипотезе — {i.data.get('expected')}; "
                 f"по данным — {i.data.get('observed')}"
                 for i in ins if i.segment_code == seg and (i.accepted or i.source == "user")]
        if lines:
            out[f"{seg} инсайты интервью"] = " | ".join(lines)
    return out


async def results_package(project_id: str) -> dict[str, Any]:
    """Пакет результатов для следующей итерации (RESULTS_PACKAGE_SPEC.md, формат 1.0)."""
    val = await validation(project_id)
    async with SessionLocal() as s:
        ins = (await s.scalars(select(Insight).where(Insight.project_id == project_id))).all()
    return dict(
        format_version="1.0", project_id=project_id, generated_at=datetime.now(UTC).isoformat(),
        hypothesis_results=[dict(hypothesis_id=v["hypothesis_id"] if "hypothesis_id" in v else v["hypothesisId"],
                                 segment_id=v["segmentId"], kind=v["kind"], n_interviews=v["nInterviews"],
                                 status=v["status"], percent=v["percent"],
                                 components=[dict(component_id=c["componentId"], slot=c["slot"], statement=c["text"],
                                                  status=c["status"], k=c["k"], c=c["c"], ri_only=c["riOnly"],
                                                  verification_method="pilot" if c["pilot"] else "interview")
                                             for c in v["components"]]) for v in val],
        insights=[dict(i.data, segment_id=i.segment_code, level=i.level, accepted=i.accepted, source=i.source) for i in ins],
        gaps=[dict(segment_id=v["segmentId"], component_id=c["componentId"], reason=c["status"])
              for v in val for c in v["components"] if c["status"] in ("not_tested", "insufficient") and not c["pilot"]],
    )


# ------------------------------------------------------------------ документы
def _hyp_md(lines: list[dict[str, Any]]) -> list[str]:
    return [f"- **{SLOT_LABEL.get(x['slot'], x['slot'])}:** {(x.get('lead') or '') + ' ' if x.get('lead') else ''}{x['text']}"
            for x in lines]


async def markdown(project_id: str, kind: str) -> str:
    async with SessionLocal() as s:
        p = await s.get(Project, project_id)
        st = {r.stage: r.response for r in (await s.scalars(select(DesignStage).where(
            DesignStage.project_id == project_id))).all()}
        ins = (await s.scalars(select(Insight).where(Insight.project_id == project_id).order_by(Insight.id))).all()
    assert p is not None
    segs, hyps = design.selected(st.get("segments", {}), st.get("hypotheses", {}), p.selection)
    label = {x["segment_id"]: f"Сегмент {n}" for n, x in enumerate(segs, 1)}
    md: list[str] = []
    if kind == "scenario":
        md += [f"# Сценарий интервью. {p.name}", ""]
        for sc in st.get("scenarios", {}).get("scenarios", []):
            md += [f"## {label.get(sc['segment_id'], sc['segment_id'])}: {sc['title']}", ""]
            section = None
            for it in sc["items"]:
                if it.get("section") != section:
                    section = it.get("section")
                    md += ["", f"### {section}", ""]
                md.append(f"{it['row_no']}. {design.plain_question(it['question'])}")
                if it.get("hint"):
                    md.append(f"   *Подсказка: {it['hint']}*")
            md.append("")
        return "\n".join(md)

    d = st.get("design", {}).get("product_description") or {}
    if kind == "design":
        md += [f"# Дизайн исследования. {p.name}", "", "## 1. Описание продукта", "",
               f"**Продукт:** {d.get('product_name', p.context.get('product', ''))}", "",
               f"**Ключевая функция:** {d.get('key_function', p.context.get('function', ''))}", "",
               f"**Проблема и потери:** {d.get('problem_and_losses', '')}", "",
               f"**Текущие способы решения:** {d.get('current_solutions', '')}", "",
               f"**Желаемый результат и эффект:** {d.get('desired_outcome_and_effect', '')}", "",
               f"**Цель исследования:** {d.get('research_goal', p.context.get('decision', ''))}", "",
               "## 2. Сегменты и гипотезы", ""]
        offers = {o["segment_id"]: o for o in st.get("offers", {}).get("offers", [])}
        for sg in segs:
            md += [f"### {label[sg['segment_id']]}", "", f"**{KIND_TITLE['segment']}:** {sg['text']}", ""]
            for h in hyps:
                if h["segment_id"] == sg["segment_id"]:
                    md += [f"**{KIND_TITLE['value']}:** {h['text']}", ""]
            o = offers.get(sg["segment_id"])
            if o:
                md += ["#### Поиск респондентов", "", f"**Кого ищем:** {o['who_to_find']}", "",
                       f"**Сколько интервью:** {o.get('interview_count') or '—'}", ""]
                md += ["**Признаки отбора:**", *[f"- {x}" for x in o["selection_criteria"]], ""]
                md += ["**Фильтр-вопросы:**", *[f"- {x}" for x in o["screening_questions"]], ""]
                md += ["**Где искать:**", *[f"- {'Сначала' if x['step_no'] == 1 else 'Затем'}: {x['channel']}"
                                            for x in o["search_sequence"]], ""]
                md += [f"**Персональный оффер:** {o['personal_offer']}", "", f"**Оффер для посева:** {o['seeding_offer']}", ""]
        return "\n".join(md)

    # отчёт
    val = await validation(project_id)
    ref = reformulated(st, p.selection)
    md += [f"# Отчёт CustDev-исследования. {p.name}", "", "## Продукт", "",
           f"{d.get('product_name') or p.context.get('product', '')}. {d.get('key_function') or p.context.get('function', '')}",
           "", f"**Цель исследования:** {d.get('research_goal') or p.context.get('decision', '')}", "",
           "## Сегменты и гипотезы", ""]
    for seg in [x["segment_id"] for x in segs]:
        md += [f"### {label[seg]}", ""]
        if seg in ref:
            md += ["#### Актуальные гипотезы", "", f"**{KIND_TITLE['segment']}**", *_hyp_md(ref[seg]["segment"]), "",
                   f"**{KIND_TITLE['value']}**", *_hyp_md(ref[seg]["value"]), ""]
        md += ["#### Проверка исходных гипотез", ""]
        for v in [v for v in val if v["segmentId"] == seg]:
            pct = f"{v['percent']:g} %" if v["percent"] is not None else "нет данных"
            md += [f"**{KIND_TITLE[v['kind']]}** — {pct}, интервью: {v['nInterviews']}", "",
                   "| Элемент | Компонент | За / против | Статус |", "|---|---|---|---|"]
            md += [f"| {SLOT_LABEL.get(c['slot'], c['slot'])} | {c['text']} | {c['k']:g} / {c['c']:g} | "
                   f"{'Нужен пилот' if c['pilot'] and c['status'] == 'not_tested' else STATUS_LABEL[c['status']]} |"
                   for c in v["components"]]
            md.append("")
    md += ["## Аналитика", "", "### А1. Что проверяли", ""]
    for sg in segs:
        md += [f"- {label[sg['segment_id']]}: {sg['text']}"]
        md += [f"  - {h['text']}" for h in hyps if h["segment_id"] == sg["segment_id"]]
    md += ["", "### А2. Инсайты", ""]
    for i in ins:
        d2 = i.data
        md += [f"**{label.get(i.segment_code, i.segment_code)} · {d2.get('element') or ''} · "
               f"{d2.get('relation_expert') or ''}** — {d2.get('title') or d2.get('insight')}", "",
               f"- В гипотезе: {d2.get('expected')}", f"- По данным: {d2.get('observed')}"]
        if d2.get("explanation"):
            md.append(f"- Почему: {d2['explanation']}")
        md += [f"- «{e['quote']}» — {e.get('respondent_id')}" for e in (d2.get("evidence") or [])[:3] if e.get("quote")]
        md.append("")
    md += ["### А3. Как изменились гипотезы", ""]
    changes = [(seg, c) for seg, r in ref.items() for c in r["changes"]]
    if not changes:
        md.append("Гипотезы ещё не переформулированы по итогам интервью.")
    for seg, c in changes:
        md += [f"- {label.get(seg, seg)}, {KIND_TITLE[c['kind']].lower()}, {SLOT_LABEL.get(c['slot'], c['slot'])}: "
               f"было «{c['before']}» → стало «{c['after']}»"]
    return "\n".join(md) + "\n"


def docx_from_markdown(md: str) -> bytes:
    """Простой перевод нашего markdown (заголовки, списки, таблицы, **жирный**) в .docx."""
    from docx import Document

    doc = Document()
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        if not table_rows:
            return
        t = doc.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        t.style = "Table Grid"
        for r, row in enumerate(table_rows):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
        table_rows.clear()

    def add_runs(par: Any, text: str) -> None:
        for n, part in enumerate(re.split(r"\*\*", text)):
            run = par.add_run(part.replace("*", ""))
            run.bold = n % 2 == 1

    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(set(c) <= {"-"} for c in cells):
                table_rows.append(cells)
            continue
        flush_table()
        if m := re.match(r"^(#{1,4}) (.*)", line):
            doc.add_heading(m.group(2), level=min(len(m.group(1)), 4) - (1 if len(m.group(1)) > 1 else 0))
        elif m := re.match(r"^(\s*)- (.*)", line):
            add_runs(doc.add_paragraph(style="List Bullet 2" if m.group(1) else "List Bullet"), m.group(2))
        elif line.strip():
            add_runs(doc.add_paragraph(), line.strip())
    flush_table()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
