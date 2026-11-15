"""Обёртка над модулем коллеги (icust_module v1.0, сервис `design` в compose; контракт — design/icust_module/CONTRACT.md).

Модуль без состояния: на вход каждого этапа — анкета и результаты предыдущих этапов. Ответы этапов храним как есть
в design_stages, выбор пользователя — в projects.selection. При переходе к интервью дизайн фиксируется (lock_design):
выбранные гипотезы раскладываются по слотам в hypotheses, сценарий — в plan_questions, дальше работает анализ (ИГ1–ИГ3).
"""
import re
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import DesignStage, Hypothesis, PlanQuestion, Project

TIMEOUT = httpx.Timeout(1800, connect=30)  # «гипотезы ценности» идут до нескольких минут, на тайм-аутах провайдера дольше

# Связки формул модуля: сегмент «[Б], которые [Б2] стремятся [Б1], чтобы [Д]»;
# ценность «Наш продукт [А] помогает [Б], которые [Б2], решить [В], приводящую к [В1], чтобы [Б1] за счёт [Г] и достичь [Д] с [Д1]»
SEGMENT_SLOTS = [("role", None), ("situation", "которые"), ("job", "стремятся"), ("outcome", "чтобы")]
VALUE_SLOTS = [("product", "Наш продукт"), ("role", "помогает"), ("situation", "которые"), ("problem", "решить"),
               ("losses", "приводящую к"), ("job", "чтобы"), ("mechanism", "за счёт"), ("outcome", "и достичь"),
               ("effect", "с")]
SLOT_CODE = {"mechanism": "function"}  # у нас слот Г называется function (как в макете и ИГ1)


class DesignError(RuntimeError):
    pass


def product_input(ctx: dict[str, Any]) -> dict[str, Any]:
    """Анкета экрана 03 → ProductInput модуля. «Роль» — группы потребителей по одной на строку (или через «;»)."""
    groups = [g.strip(" -•\t") for g in re.split(r"[\n;]+", ctx.get("role") or "") if g.strip(" -•\t")]
    return dict(product=ctx.get("product", ""), groups=groups or [ctx.get("role", "")], job=ctx.get("job", ""),
                situation=ctx.get("situation", ""), problem=ctx.get("problem", ""), losses=ctx.get("losses", ""),
                mechanism=ctx.get("function", ""), outcome=ctx.get("outcome", ""), effect=ctx.get("effect") or None,
                alternatives=ctx.get("alternatives", ""), decision=ctx.get("decision", ""))


async def call(path: str, body: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=get_settings().design_url, timeout=TIMEOUT) as c:
        try:
            r = await c.post(path, json=body)
        except httpx.HTTPError as e:
            raise DesignError(f"Модуль генерации недоступен: {e!r}") from e
        if r.status_code >= 400:
            raise DesignError(f"Модуль генерации {path}: {r.status_code} {r.text[:400]}")
        data: dict[str, Any] = r.json()
        return data


async def stage(s: AsyncSession, project_id: str, name: str) -> dict[str, Any]:
    row = (await s.scalars(select(DesignStage).where(DesignStage.project_id == project_id,
                                                     DesignStage.stage == name))).first()
    return row.response if row else {}


async def save_stage(s: AsyncSession, project_id: str, name: str, response: dict[str, Any]) -> None:
    row = (await s.scalars(select(DesignStage).where(DesignStage.project_id == project_id,
                                                     DesignStage.stage == name))).first()
    if row is None:
        s.add(DesignStage(project_id=project_id, stage=name, response=response))
    else:
        row.response = response


def _regen(summary: dict[str, str] | None) -> dict[str, Any]:
    return {"initial_generation": summary is None, "interview_summary": summary}


# ------------------------------------------------------------------ этапы 1–2: сегменты и гипотезы ценности
async def run_hypotheses(project_id: str, summary: dict[str, str] | None = None) -> dict[str, int]:
    """Сегменты → гипотезы ценности по всем трём. summary — повторная генерация после анализа (экран 11.2)."""
    async with SessionLocal() as s:
        project = await s.get(Project, project_id)
        if project is None:
            raise DesignError("Проект не найден")
        if project.locked and summary is None:
            raise DesignError("Дизайн зафиксирован: интервью уже идут по выбранным гипотезам")
        product = product_input(project.context)
        seg = await call("/segments", {"product": product, "n_segments": 3, **_regen(summary)})
        hyp = await call("/value-hypotheses", {"product": product, "segments": seg["segments"], "n_per_segment": 2,
                                               **_regen(summary)})
        if summary is not None:  # новая итерация: исходный дизайн и результаты не трогаем
            await save_stage(s, project_id, "reformulate", {"segments": seg, "hypotheses": hyp, "summary": summary})
            await s.commit()
            return {"segments": len(seg["segments"]), "hypotheses": len(hyp["hypotheses"])}
        await save_stage(s, project_id, "segments", seg)
        await save_stage(s, project_id, "hypotheses", hyp)
        for later in ("scenarios", "offers", "design"):  # прежний сценарий относится к прежним гипотезам
            await s.execute(delete(DesignStage).where(DesignStage.project_id == project_id, DesignStage.stage == later))
        # по умолчанию выбраны прошедшие проверку сегменты (до двух) и первая прошедшая гипотеза каждого
        passed = [x["segment_id"] for x in seg["segments"] if (x.get("check") or {}).get("passed")]
        chosen = passed[:2] or [x["segment_id"] for x in seg["segments"][:1]]
        values: dict[str, list[str]] = {}
        for sid in chosen:
            own = [h for h in hyp["hypotheses"] if h["segment_id"] == sid]
            best = next((h for h in own if (h.get("check") or {}).get("passed")), own[0] if own else None)
            values[sid] = [best["hypothesis_id"]] if best else []
        project.selection = {"segments": chosen, "values": values}
        await s.commit()
        return {"segments": len(seg["segments"]), "hypotheses": len(hyp["hypotheses"])}


def selected(seg: dict[str, Any], hyp: dict[str, Any], selection: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    seg_ids = list(selection.get("segments", []))
    segs = sorted((x for x in seg.get("segments", []) if x["segment_id"] in seg_ids),
                  key=lambda x: seg_ids.index(x["segment_id"]))
    values = selection.get("values", {})
    hyps = [h for h in hyp.get("hypotheses", []) if h["hypothesis_id"] in values.get(h["segment_id"], [])
            and h["segment_id"] in seg_ids]
    return segs, hyps


# ------------------------------------------------------------------ этапы 3–5: сценарий, офферы, дизайн
async def run_scenario(project_id: str) -> dict[str, Any]:
    async with SessionLocal() as s:
        project = await s.get(Project, project_id)
        if project is None:
            raise DesignError("Проект не найден")
        if project.locked:
            raise DesignError("Дизайн зафиксирован: интервью уже идут по этому сценарию")
        segs, hyps = selected(await stage(s, project_id, "segments"), await stage(s, project_id, "hypotheses"),
                              project.selection)
        if not segs or not hyps:
            raise DesignError("Не выбраны сегменты и гипотезы ценности")
        product = product_input(project.context)
        sc = await call("/scenarios", {"product": product, "segments": segs, "hypotheses": hyps})
        await save_stage(s, project_id, "scenarios", sc)
        await s.commit()
        of = await call("/offers", {"product": product, "segments": segs, "hypotheses": hyps, "scenarios": sc["scenarios"]})
        await save_stage(s, project_id, "offers", of)
        await s.commit()
        de = await call("/design", {"product": product, "segments": segs, "hypotheses": hyps,
                                    "scenarios": sc["scenarios"], "offers": of["offers"]})
        await save_stage(s, project_id, "design", de)
        await s.commit()
        return {"scenarios": len(sc["scenarios"]), "complete": sc["complete"] and of["complete"] and de["complete"]}


# ------------------------------------------------------------------ фиксация дизайна перед интервью
def slot_lines(elements: dict[str, Any] | None, text: str, kind: str) -> list[dict[str, Any]]:
    """Элементы формулы (дословные фрагменты текста гипотезы) → строки слотов [{slot, lead, text}]."""
    slots = SEGMENT_SLOTS if kind == "segment" else VALUE_SLOTS
    lines: list[dict[str, Any]] = []
    for key, lead in slots:
        frag = str((elements or {}).get(key) or "").strip()
        if not frag:
            continue
        if lead and frag.lower().startswith(lead.lower()):  # связка уже внутри фрагмента
            lead = None
        lines.append(dict(slot=SLOT_CODE.get(key, key), lead=lead, text=frag))
    return lines or [dict(slot="role", lead=None, text=text)]  # разбиения нет — гипотеза одним слотом


def plain_question(q: str) -> str:
    """Вставки модуля помечены <…>: для интервьюера и ИГ1 — текст без скобок."""
    return re.sub(r"<([^<>]*)>", r"\1", q).strip()


async def lock_design(project_id: str) -> dict[str, int]:
    """Выбранные гипотезы → hypotheses (по слотам), сценарий → plan_questions. Один раз, до интервью."""
    async with SessionLocal() as s:
        project = await s.get(Project, project_id)
        if project is None:
            raise DesignError("Проект не найден")
        if project.locked:
            return {"already_locked": 1}
        segs, hyps = selected(await stage(s, project_id, "segments"), await stage(s, project_id, "hypotheses"),
                              project.selection)
        scenarios = (await stage(s, project_id, "scenarios")).get("scenarios", [])
        if not segs or not hyps or not scenarios:
            raise DesignError("Сначала выберите гипотезы и соберите сценарий")
        await s.execute(delete(Hypothesis).where(Hypothesis.project_id == project_id))
        await s.execute(delete(PlanQuestion).where(PlanQuestion.project_id == project_id))
        for sg in segs:
            s.add(Hypothesis(project_id=project_id, segment_code=sg["segment_id"], code=sg["segment_id"], kind="segment",
                             lines=slot_lines(sg.get("elements"), sg["text"], "segment")))
        for h in hyps:
            s.add(Hypothesis(project_id=project_id, segment_code=h["segment_id"],
                             code=f"{h['segment_id']}-{h['hypothesis_id']}", kind="value",
                             lines=slot_lines(h.get("elements"), h["text"], "value")))
        n_q = 0
        for sc in scenarios:
            for it in sc["items"]:
                s.add(PlanQuestion(project_id=project_id, segment_code=sc["segment_id"],
                                   question_id=f"Q{it['row_no']:02d}", section=it.get("section") or "",
                                   text=plain_question(it["question"]), checks=[]))
                n_q += 1
        project.locked = True
        await s.commit()
        return {"hypotheses": len(segs) + len(hyps), "questions": n_q}
