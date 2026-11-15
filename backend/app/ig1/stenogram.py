"""Стенограмма «вопрос — ответ» (экран 09, MVP_PLAN.md раздел 8, п. 4): по каждому интервью сегмента —
короткий ответ респондента на каждый вопрос сценария (почти дословно, с таймкодом), затем по сегменту —
«Выводы по сегменту» по каждому вопросу. Вход — обезличенные реплики (шаг 2) с разметкой вопросов (шаг 3б).
"""
import json
from typing import Any

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.ig1.pipeline import _llm
from app.models import Interview, PlanQuestion, StenogramRow, Turn

SYSTEM_ANSWERS = """Ты помогаешь исследователю разложить проблемное интервью по вопросам сценария.
Для каждого вопроса сценария найди в расшифровке ответ респондента (реплики respondent после вопроса или там, где тема обсуждалась)
и запиши его коротко — до 20 слов, максимально близко к словам респондента, от первого лица, без оценок.
Если вопрос не обсуждался — не включай его. turn_index — номер реплики респондента, где главный ответ.
Форма ответа: {"answers": [{"question_id": "Q05", "answer": "...", "turn_index": 12}]}
Ответь ТОЛЬКО одним JSON-объектом, без markdown. Пиши по-русски."""

SYSTEM_SUMMARY = """Ты исследователь custdev. По каждому вопросу сценария даны короткие ответы респондентов одного сегмента.
Сформулируй «вывод по сегменту» — одно предложение до 25 слов: что общего и чем отличаются ответы, с числами «N из M», где уместно
(M — число ответивших на вопрос). Не выдумывай того, чего нет в ответах.
Форма ответа: {"summaries": [{"question_id": "Q05", "summary": "..."}]}
Ответь ТОЛЬКО одним JSON-объектом, без markdown. Пиши по-русски."""


async def run_segment(project_id: str, segment: str) -> dict[str, int]:
    async with SessionLocal() as s:
        qs = (await s.scalars(select(PlanQuestion).where(PlanQuestion.project_id == project_id,
                                                         PlanQuestion.segment_code == segment)
                              .order_by(PlanQuestion.question_id))).all()
        ivs = (await s.scalars(select(Interview).where(Interview.project_id == project_id, Interview.segment_code == segment,
                                                       Interview.status == "processed").order_by(Interview.id))).all()
        plan = [dict(question_id=q.question_id, text=q.text) for q in qs]
        valid = {q.question_id for q in qs}
        answers: dict[str, dict[str, Any]] = {q.question_id: {} for q in qs}
        llm = _llm(project_id)
        try:
            for iv in ivs:
                turns = (await s.scalars(select(Turn).where(Turn.interview_id == iv.id).order_by(Turn.turn_index))).all()
                start = {t.turn_index: t.start_sec for t in turns}
                view = [dict(turn_index=t.turn_index, speaker_role=t.speaker_role, text=t.text_anon or t.text,
                             **({"question_ids": t.question_ids} if t.question_ids else {})) for t in turns]
                user = ("Вопросы сценария:\n" + json.dumps(plan, ensure_ascii=False) +
                        "\n\nРасшифровка (question_ids у реплик интервьюера — какой вопрос сценария задан):\n" +
                        "\n".join(json.dumps(v, ensure_ascii=False) for v in view))
                obj = await llm.call("sten", SYSTEM_ANSWERS, user)
                for a in obj.get("answers") or []:
                    qid, text = a.get("question_id"), (a.get("answer") or "").strip()
                    if qid in valid and text:
                        answers[qid][iv.respondent_code] = {"text": text, "time": start.get(a.get("turn_index"))}
            summaries: dict[str, str] = {}
            asked = [dict(question_id=q.question_id, question=q.text,
                          answers=[v["text"] for v in answers[q.question_id].values()])
                     for q in qs if answers[q.question_id]]
            if asked:
                user = (f"Сегмент {segment}, интервью: {len(ivs)}.\n\n" +
                        "\n".join(json.dumps(x, ensure_ascii=False) for x in asked))
                obj = await llm.call("sten_sum", SYSTEM_SUMMARY, user)
                summaries = {x["question_id"]: x.get("summary", "") for x in obj.get("summaries") or []
                             if x.get("question_id") in valid}
        finally:
            await llm.aclose()
        await s.execute(delete(StenogramRow).where(StenogramRow.project_id == project_id,
                                                   StenogramRow.segment_code == segment))
        for q in qs:
            if answers[q.question_id]:
                s.add(StenogramRow(project_id=project_id, segment_code=segment, question_id=q.question_id,
                                   summary=summaries.get(q.question_id, ""), answers=answers[q.question_id]))
        await s.commit()
        return {"interviews": len(ivs), "questions": sum(bool(v) for v in answers.values())}


async def run_project(project_id: str) -> list[dict[str, int]]:
    async with SessionLocal() as s:
        segments = sorted(set((await s.scalars(select(Interview.segment_code).where(
            Interview.project_id == project_id, Interview.status == "processed"))).all()))
    return [await run_segment(project_id, seg) for seg in segments]
