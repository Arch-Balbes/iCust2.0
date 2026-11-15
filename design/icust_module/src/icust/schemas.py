"""Схемы входа и выхода этапов (Pydantic). Используются FastAPI для валидации и документации (/docs).

Функции этапов работают со словарями той же структуры; API переводит запрос в dict и ответ — в эти модели.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ================================================================ общее
class ProductInput(BaseModel):
    """Анкета продукта (поля А–Ж)."""
    product: str = Field(..., description="{А} Название продукта / фичи")
    groups: list[str] = Field(..., min_length=1, description="{Б} Первоначальные группы потенциальных потребителей — по одной в элементе; разбор исходного текста на группы делает бэкенд")
    job: str = Field(..., description="{Б1} Потребительская задача")
    situation: str = Field(..., description="{Б2} Ситуация и условия выполнения работы")
    problem: str = Field(..., description="{В} Гипотеза проблемы")
    losses: str = Field(..., description="{В1} Предполагаемые измеримые потери")
    mechanism: str = Field(..., description="{Г} Механизм / функция предлагаемого решения")
    outcome: str = Field(..., description="{Д} Желаемый результат потребителя")
    effect: str | None = Field(None, description="{Д1} Проверяемый эффект продуктового решения (опционально)")
    alternatives: str = Field(..., description="{Е} Текущие альтернативы и ограничения")
    decision: str = Field(..., description="{Ж} Решение по результатам исследования")


class RegenerationParams(BaseModel):
    """Повторная генерация после анализа интервью (общие поля запросов этапов)."""
    initial_generation: bool = Field(True, description="true — первичная генерация; false — повторная, после анализа интервью")
    interview_summary: dict[str, str] | None = Field(None, description="Сводка анализа интервью; обязательна при initial_generation=false. Каждое поле идёт в промпт строкой «поле: значение»")


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Meta(BaseModel):
    """Расход и предупреждения этапа."""
    usage: Usage
    llm_calls: int = Field(..., description="Число вызовов LLM (генерация, оценка, разбиение на элементы)")
    cached_calls: int = Field(0, description="Из них взято из кэша (в проде кэш выключен — 0)")
    models: list[str]
    warnings: list[str] = Field(default_factory=list, description="Добор непрошедшими, недословное разбиение, неудачные попытки и т. п.")


class FailedCriterion(BaseModel):
    criterion_no: int
    passed: bool = False
    reason: str


class QualityCheck(BaseModel):
    """Результат проверки оценщиком: passed=True — выполнены все критерии."""
    passed: bool
    failed_criteria: list[FailedCriterion] = Field(default_factory=list)


# ================================================================ этап 1: сегменты
class SegmentElements(BaseModel):
    """Элементы формулы сегмента: [Б], которые [Б2] стремятся [Б1], чтобы [Д]."""
    role: str | None = Field(None, description="{Б} Группа потребителей в определённой роли")
    situation: str | None = Field(None, description="{Б2} Ситуация и условия")
    job: str | None = Field(None, description="{Б1} Потребительская задача")
    outcome: str | None = Field(None, description="{Д} Объединяющий желаемый результат")


class Segment(BaseModel):
    segment_id: str = Field(..., examples=["SEG01"])
    text: str = Field(..., description="Гипотеза сегмента одним предложением")
    elements: SegmentElements | None = None
    elements_verified: bool | None = Field(None, description="Разбиение дословное и собирается обратно в text")
    check: QualityCheck | None = None


class SegmentsRequest(RegenerationParams):
    product: ProductInput
    n_segments: Literal[3] = Field(3, description="Пока только 3")
    dedupe: bool = Field(False, description="false — без фильтра дублей (как в экспериментах); true — сегмент, совпадающий с уже взятым по тексту или по смысловой близости ≥ 0,95, пропускается")


class SegmentsResponse(BaseModel):
    segments: list[Segment] = Field(..., description="Ровно 3")
    complete: bool = Field(..., description="false — за 3 генерации не набралось 3 прошедших проверку; недостающие добраны лучшими непрошедшими")
    message: str | None = None
    meta: Meta


# ================================================================ этап 2: гипотезы ценности
class ValueHypothesisElements(BaseModel):
    """Элементы формулы: Наш продукт [А] помогает [Б], которые [Б2], решить [В], приводящую к [В1], чтобы [Б1] за счёт [Г] и достичь [Д] с [Д1]."""
    product: str | None = None
    role: str | None = None
    situation: str | None = None
    problem: str | None = None
    losses: str | None = None
    job: str | None = None
    mechanism: str | None = None
    outcome: str | None = None
    effect: str | None = Field(None, description="null, если в гипотезе нет части с эффектом")


class ValueHypothesis(BaseModel):
    hypothesis_id: str = Field(..., examples=["H01"], description="H01…H06, сквозная нумерация")
    segment_id: str
    text: str
    elements: ValueHypothesisElements | None = None
    elements_verified: bool | None = None
    check: QualityCheck | None = None


class HypothesesRequest(RegenerationParams):
    product: ProductInput
    segments: list[Segment] = Field(..., min_length=1, description="Сегменты из ответа этапа 1")
    n_per_segment: Literal[2] = Field(2, description="Пока только 2")
    dedupe: bool = Field(False, description="Фильтр дублей гипотез внутри сегмента (как у сегментов)")


class HypothesesResponse(BaseModel):
    hypotheses: list[ValueHypothesis]
    complete: bool
    message: str | None = None
    meta: Meta


# ================================================================ этап 3: сценарий интервью
class ScenarioItem(BaseModel):
    """Строка сценария по шаблону SCORE/JTBD."""
    row_no: int = Field(..., description="Номер строки шаблона (4–40) — стабильный ключ вопроса")
    section: str | None = Field(None, examples=["1. Фильтр-вопросы"])
    topic: str | None = Field(None, examples=["Опыт решения проблемы"])
    question: str = Field(..., description="Текст шаблона дословно; сгенерированные вставки — в <…>; строки 4 и 40 — целиком, многострочные")
    hint: str | None = Field(None, description="Подсказка интервьюеру из шаблона")


class Scenario(BaseModel):
    scenario_id: str = Field(..., examples=["SEG01-SC"])
    segment_id: str
    title: str = Field(..., description="Роль сегмента (элемент role) или ID сегмента")
    items: list[ScenarioItem]


class ScenarioRequest(RegenerationParams):
    product: ProductInput
    segments: list[Segment] = Field(..., min_length=1)
    hypotheses: list[ValueHypothesis] = Field(..., min_length=1)


class ScenarioResponse(BaseModel):
    scenarios: list[Scenario] = Field(..., description="По одному на сегмент")
    complete: bool = Field(..., description="false — для какого-то сегмента сценарий не сгенерирован за 3 попытки (возвращён шаблон без вставок); нужен повторный запуск")
    meta: Meta


# ================================================================ этап 4: респонденты и офферы
class SearchStep(BaseModel):
    step_no: int = Field(..., description="1 — «Сначала», 2+ — «Затем»")
    channel: str
    offer_type: Literal["personal", "seeding"]


class ChannelRecommendation(BaseModel):
    title: str = Field(..., description="Площадка")
    description: str = Field(..., description="Кто там и как искать, поисковые запросы")
    offer_type: Literal["personal", "seeding"] | None = None
    url: str | None = Field(None, description="Только корневой домен площадки из списка разрешённых, иначе null")


class SegmentOffer(BaseModel):
    segment_id: str
    who_to_find: str = Field(..., description="«Кого ищем»")
    interview_count: Literal["15–20", "5"] | None = Field(..., description="«15–20» (B2C) или «5» (B2B); null — оффер не сгенерирован")
    interview_count_note: str | None = Field(None, description="Пояснение к количеству (для B2B)")
    selection_criteria: list[str] = Field(..., description="Признаки отбора")
    screening_questions: list[str] = Field(..., description="Фильтр-вопросы из сценария сегмента (строки 4–5), копия кодом")
    search_sequence: list[SearchStep]
    channel_recommendations: list[ChannelRecommendation]
    personal_offer: str
    seeding_offer: str


class FixedChannel(BaseModel):
    title: str
    description: str
    url: str


class FixedChannels(BaseModel):
    caption: str
    channels: list[FixedChannel]


class OfferRequest(RegenerationParams):
    product: ProductInput
    segments: list[Segment] = Field(..., min_length=1)
    hypotheses: list[ValueHypothesis] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list, description="Сценарии из этапа 3 — из них берутся фильтр-вопросы")


class OfferResponse(BaseModel):
    offers: list[SegmentOffer] = Field(..., description="По одному на сегмент")
    fixed_channels: FixedChannels = Field(..., description="Статический блок общих площадок — одинаковый для всех исследований")
    complete: bool = Field(..., description="false — для какого-то сегмента оффер не сгенерирован за 3 попытки (поля пустые); нужен повторный запуск")
    meta: Meta


# ================================================================ этап 5: дизайн исследования
class ProductDescription(BaseModel):
    product_name: str = Field(..., description="{А} из анкеты")
    key_function: str = Field(..., description="{Г} из анкеты")
    research_goal: str = Field(..., description="{Ж} из анкеты")
    problem_and_losses: str = Field(..., description="LLM: «[Б], которые [Б2], при [Б1] сталкиваются с проблемой [В], что приводит к [В1]»")
    current_solutions: str = Field(..., description="LLM: «Сейчас, чтобы [Б1], [Б] [Е], но это не решает проблему [В]»")
    desired_outcome_and_effect: str = Field(..., description="LLM: «[Б] хотят [Д], с [Д1] вместо [В1]»")


class DesignSegment(BaseModel):
    segment: Segment
    value_hypotheses: list[ValueHypothesis]
    scenario_id: str | None = None
    offer: SegmentOffer | None = None


class DesignRequest(BaseModel):
    product: ProductInput
    segments: list[Segment] = Field(..., min_length=1)
    hypotheses: list[ValueHypothesis] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    offers: list[SegmentOffer] = Field(default_factory=list)


class DesignResponse(BaseModel):
    product_description: ProductDescription
    segments: list[DesignSegment] = Field(..., description="Результаты этапов кодом, без изменений; документ собирает бэкенд")
    complete: bool = Field(..., description="false — раздел 1 не сгенерирован за 3 попытки (поля пустые); нужен повторный запуск")
    meta: Meta
