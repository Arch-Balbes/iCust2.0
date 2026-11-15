"""FastAPI-приложение: по маршруту на этап.

Запуск (из папки src, переменные окружения — см. README):
    uvicorn icust.api:app --host 0.0.0.0 --port 8000
Документация: http://127.0.0.1:8000/docs

Обработчики синхронные (def): FastAPI выполняет их в пуле потоков, вызовы LLM внутри этапов идут параллельно.
База знаний загружается один раз при старте.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import __version__
from .knowledge_base import load_knowledge_base
from .schemas import (DesignRequest, DesignResponse, HypothesesRequest, HypothesesResponse, OfferRequest,
                      OfferResponse, ScenarioRequest, ScenarioResponse, SegmentsRequest, SegmentsResponse)
from .stages import build_design, generate_offers, generate_scenarios, generate_segments, generate_value_hypotheses

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["kb"] = load_knowledge_base()
    yield
    STATE.clear()


app = FastAPI(title="iCust — дизайн CustDev-исследования", version=__version__, lifespan=lifespan)


def _kb():
    if "kb" not in STATE:
        raise HTTPException(503, "База знаний не загружена")
    return STATE["kb"]


def _dump(models) -> list[dict]:
    return [m.model_dump() for m in models]


def _regen(req) -> dict:
    if not req.initial_generation and not req.interview_summary:
        raise HTTPException(422, "initial_generation=false требует interview_summary")
    return {"initial_generation": req.initial_generation, "interview_summary": req.interview_summary}


@app.get("/health")
def health():
    return {"status": "ok" if "kb" in STATE else "loading", "version": __version__}


@app.post("/segments", response_model=SegmentsResponse, summary="1. Гипотезы сегментов ЦА")
def segments(req: SegmentsRequest):
    return generate_segments(req.product.model_dump(), _kb(), n_segments=req.n_segments, dedupe=req.dedupe, **_regen(req))


@app.post("/value-hypotheses", response_model=HypothesesResponse, summary="2. Гипотезы ценности продукта")
def value_hypotheses(req: HypothesesRequest):
    return generate_value_hypotheses(req.product.model_dump(), _dump(req.segments), _kb(),
                                     n_per_segment=req.n_per_segment, dedupe=req.dedupe, **_regen(req))


@app.post("/scenarios", response_model=ScenarioResponse, summary="3. Сценарий интервью (SCORE/JTBD)")
def scenarios(req: ScenarioRequest):
    return generate_scenarios(req.product.model_dump(), _dump(req.segments), _dump(req.hypotheses), _kb(), **_regen(req))


@app.post("/offers", response_model=OfferResponse, summary="4. Поиск респондентов и офферы")
def offers(req: OfferRequest):
    return generate_offers(req.product.model_dump(), _dump(req.segments), _dump(req.hypotheses), _dump(req.scenarios),
                           _kb(), **_regen(req))


@app.post("/design", response_model=DesignResponse, summary="5. Дизайн исследования")
def design(req: DesignRequest):
    return build_design(req.product.model_dump(), _dump(req.segments), _dump(req.hypotheses), _dump(req.scenarios),
                        _dump(req.offers), _kb())
