"""Шаг 1 — распознавание и диаризация через Nexara (https://docs.nexara.ru).

Асинхронный режим: POST /audio/transcriptions/async (файл до 3 ГБ) → job_id → опрос GET …/async/{job_id}
до status=complete|error. task=diarize, response_format=verbose_json, roles — разметка ролей по содержанию
разговора (тарифицируется отдельно; если не сработала, остаются метки speaker_N — тогда роль определяем сами).
"""
import asyncio
import json
from typing import Any

import httpx

from app.core.config import get_settings

ROLE_INTERVIEWER = "Интервьюер"
ROLE_RESPONDENT = "Респондент"
ROLES = {
    ROLE_INTERVIEWER: "Проводит исследовательское интервью: задаёт вопросы о опыте, привычках и проблемах собеседника.",
    ROLE_RESPONDENT: "Отвечает на вопросы: рассказывает о своём опыте, ситуациях, трудностях и решениях.",
}
POLL_SECONDS = 10
MAX_WAIT_SECONDS = 3 * 60 * 60
MAX_NET_FAILURES = 30  # ~5 минут сетевых сбоев подряд
CREATE_RETRY_PAUSES = (5, 10, 20, 40, 60, 60)  # отправка файла: ~3 минуты повторов, пока Nexara недоступна


class NexaraError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    s = get_settings()
    if not s.nexara_api_key:
        raise NexaraError("Нет NEXARA_API_KEY: проверьте iCust.env (SECRETS_ENV_FILE)")
    return httpx.AsyncClient(
        base_url=s.nexara_base_url,
        headers={"Authorization": f"Bearer {s.nexara_api_key.get_secret_value()}"},
        timeout=httpx.Timeout(600, connect=30),
    )


async def create_job(filename: str, data: bytes) -> str:
    """Отправка записи. Повторяем только то, что Nexara точно не приняла: не удалось подключиться или ответ
    429 / 502–504 (15.11.2026 две записи упали на «All connection attempts failed» при кратком сбое сети).
    Обрыв уже после отправки не повторяем — иначе можно создать вторую платную задачу."""
    async with _client() as c:
        for pause in (*CREATE_RETRY_PAUSES, None):
            try:
                r = await c.post(
                    "/audio/transcriptions/async",
                    files={"file": (filename, data)},
                    data={
                        "model": "whisper-1",
                        "task": "diarize",
                        "response_format": "verbose_json",
                        "num_speakers": "2",
                        "roles": json.dumps(ROLES, ensure_ascii=False),
                    },
                )
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if pause is None:
                    raise
                await asyncio.sleep(pause)
                continue
            if r.status_code in (429, 502, 503, 504) and pause is not None:
                await asyncio.sleep(pause)
                continue
            break
        if r.status_code >= 400:
            raise NexaraError(f"Nexara {r.status_code}: {r.text[:300]}")
        job_id = r.json().get("job_id")
        if not job_id:
            raise NexaraError(f"Nexara не вернула job_id: {r.text[:300]}")
        return str(job_id)


async def wait_job(job_id: str) -> dict[str, Any]:
    """Опрос задачи. Временные сбои сети и 5xx не обрывают ожидание (14.11.2026 расшифровка упала из-за
    кратковременной ошибки DNS на 8-й минуте): обрываем только после MAX_NET_FAILURES неудач подряд."""
    async with _client() as c:
        waited, failures = 0, 0
        while waited < MAX_WAIT_SECONDS:
            try:
                r = await c.get(f"/audio/transcriptions/async/{job_id}")
            except httpx.TransportError:
                r = None
            if r is None or r.status_code >= 500:
                failures += 1
                if failures >= MAX_NET_FAILURES:
                    raise NexaraError(f"Nexara недоступна {failures} раз подряд: задача {job_id} не дождалась ответа")
                await asyncio.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
                continue
            failures = 0
            if r.status_code >= 400:
                raise NexaraError(f"Nexara {r.status_code}: {r.text[:300]}")
            body = r.json()
            status = body.get("status")
            if status == "complete":
                result = body.get("result")
                parsed: dict[str, Any] = json.loads(result) if isinstance(result, str) else result
                return parsed
            if status == "error":
                raise NexaraError(f"Nexara: задача завершилась ошибкой: {body.get('error')}")
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
    raise NexaraError("Nexara: превышено время ожидания расшифровки")


def segments_to_turns(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Сегменты Nexara → реплики: подряд идущие сегменты одного говорящего склеиваются в одну реплику.
    Роль: метки Nexara «Интервьюер/Респондент», иначе — говорящий с наибольшей долей вопросов = интервьюер."""
    turns: list[dict[str, Any]] = []
    for seg in result.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        speaker = str(seg.get("speaker") or "speaker_0")
        if turns and turns[-1]["speaker_label"] == speaker:
            turns[-1]["text"] += " " + text
            turns[-1]["end_sec"] = float(seg.get("end") or turns[-1]["end_sec"])
            continue
        turns.append(dict(speaker_label=speaker, start_sec=float(seg.get("start") or 0),
                          end_sec=float(seg.get("end") or 0), text=text))

    labels = {t["speaker_label"] for t in turns}
    if ROLE_INTERVIEWER in labels:
        interviewer = ROLE_INTERVIEWER
    else:
        def question_share(label: str) -> float:
            own = [t for t in turns if t["speaker_label"] == label]
            return sum("?" in t["text"] for t in own) / max(1, len(own))
        interviewer = max(labels, key=question_share) if labels else ""
    for i, t in enumerate(turns):
        t["turn_index"] = i
        t["speaker_role"] = "interviewer" if t["speaker_label"] == interviewer else "respondent"
    return turns
