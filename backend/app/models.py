"""Модель данных модуля анализа интервью (ИГ1 → ИГ2): проекты, области, гипотезы со слотами, компоненты,
план интервью, записи, реплики, утверждения, пары «утверждение × компонент», журнал вызовов LLM.
Термины и поля — IG1_PIPELINE.md и PROJECT_DOMAINS.md."""
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2 (fastembed, локально)


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Created, Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # Анкета А–Ж: product, role, job, situation, problem, losses, function, outcome, effect, alternatives, decision
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress | done
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Выбор пользователя на экране «Гипотезы»: {"segments": ["SEG01"], "values": {"SEG01": ["H01"]}}
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Дизайн зафиксирован: выбранные гипотезы и сценарий перенесены в hypotheses / plan_questions (до интервью)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class DesignStage(Base):
    """Ответ модуля коллеги по этапу: segments | hypotheses | scenarios | offers | design | reformulate."""
    __tablename__ = "design_stages"
    __table_args__ = (UniqueConstraint("project_id", "stage"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectJob(Base):
    """Состояние долгой операции проекта для экранов «идёт обработка» / «не удалось»."""
    __tablename__ = "project_jobs"
    __table_args__ = (UniqueConstraint("project_id", "kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # hypotheses | scenario | prepare | stenogram | insights | reformulate
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StenogramRow(Base):
    """Стенограмма «вопрос — ответ» (экран 09): короткие ответы респондентов и вывод по сегменту."""
    __tablename__ = "stenogram_rows"
    __table_args__ = (UniqueConstraint("project_id", "segment_code", "question_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    segment_code: Mapped[str] = mapped_column(String(32))
    question_id: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, default="")
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # respondent_code → {text, time}


class Insight(Created, Base):
    """Инсайт ИГ3 (решения 06.11 и 14.11.2026): всегда относится к гипотезе одного сегмента."""
    __tablename__ = "insights"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    segment_code: Mapped[str] = mapped_column(String(32))
    insight_code: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(8), default="llm")  # llm | user
    level: Mapped[str] = mapped_column(String(16), default="candidate")  # stable | candidate
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # формат METHOD.md + правки пользователя
    comments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class Subdomain(Created, Base):
    """Справочник областей: отрасль → подобласть (PROJECT_DOMAINS.md)."""
    __tablename__ = "subdomains"
    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    industry_code: Mapped[str] = mapped_column(String(32))
    industry_name: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    added_by: Mapped[str] = mapped_column(String(16), default="catalog")  # catalog | llm
    source_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merged_into: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trained_projects: Mapped[int] = mapped_column(Integer, default=0)  # проекты с проверенной разметкой


class ProjectDomain(Created, Base):
    __tablename__ = "project_domains"
    __table_args__ = (UniqueConstraint("project_id", "subdomain_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    subdomain_code: Mapped[str] = mapped_column(ForeignKey("subdomains.code"))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(8), default="high")


class Hypothesis(Created, Base):
    """Гипотеза по слотам (наша модель, решение 13.11.2026): lines = [{slot, lead, text}]."""
    __tablename__ = "hypotheses"
    __table_args__ = (UniqueConstraint("project_id", "code", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    segment_code: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(64))            # SEG01 / SEG01-H01
    kind: Mapped[str] = mapped_column(String(16))            # segment | value
    version: Mapped[int] = mapped_column(Integer, default=1)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    components: Mapped[list["Component"]] = relationship(back_populates="hypothesis", cascade="all, delete-orphan")


class Component(Created, Base):
    """Атомарный компонент (шаг 0). component_id = <код гипотезы>:<слот>[-a|-b…]."""
    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("hypothesis_id", "component_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id", ondelete="CASCADE"))
    component_id: Mapped[str] = mapped_column(String(96))
    parent_component_id: Mapped[str] = mapped_column(String(96))
    slot: Mapped[str] = mapped_column(String(32))
    statement: Mapped[str] = mapped_column(Text)
    verification_method: Mapped[str] = mapped_column(String(16))  # interview | pilot | timed_pilot
    quantifier: Mapped[str] = mapped_column(String(16), default="occurrence")  # occurrence | typical
    auto_split: Mapped[bool] = mapped_column(Boolean, default=False)
    hypothesis: Mapped[Hypothesis] = relationship(back_populates="components")


class PlanQuestion(Created, Base):
    __tablename__ = "plan_questions"
    __table_args__ = (UniqueConstraint("project_id", "segment_code", "question_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    segment_code: Mapped[str] = mapped_column(String(32))
    question_id: Mapped[str] = mapped_column(String(32))
    section: Mapped[str] = mapped_column(String(200), default="")
    text: Mapped[str] = mapped_column(Text)
    checks: Mapped[list[str]] = mapped_column(JSONB, default=list)          # слоты из сценария
    component_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)   # шаг 3а


class Interview(Created, Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    segment_code: Mapped[str] = mapped_column(String(32))  # сегмент задаёт человек (IG1_PIPELINE)
    respondent_code: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(300))
    object_key: Mapped[str] = mapped_column(String(400))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # uploaded → transcribing → transcribed → processing → processed | error
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    nexara_job_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    asr_raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Индикатор на экране 08: доля пройденного внутри текущего статуса (0…1) и когда статус начался
    stage_progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Контрольные точки обработки (15.11.2026): утверждения шага 4 уже сохранены; номера пакетов шага 5,
    # чьи пары сохранены. «Повторить» продолжает с первого незавершённого пакета, а не с начала.
    claims_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    step5_done: Mapped[list[int]] = mapped_column(JSONB, default=list)
    turns: Mapped[list["Turn"]] = relationship(cascade="all, delete-orphan", order_by="Turn.turn_index")


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("interview_id", "turn_index"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"))
    turn_index: Mapped[int] = mapped_column(Integer)
    speaker_label: Mapped[str] = mapped_column(String(64))
    speaker_role: Mapped[str] = mapped_column(String(16))  # interviewer | respondent
    start_sec: Mapped[float] = mapped_column(Float)
    end_sec: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    text_anon: Mapped[str | None] = mapped_column(Text, nullable=True)  # шаг 2: имена → [ИМЯ]
    has_question: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # шаг 3б
    question_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    off_plan: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    leading_question: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Claim(Base):
    """Атомарное утверждение респондента (шаг 4)."""
    __tablename__ = "claims"
    __table_args__ = (UniqueConstraint("interview_id", "claim_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id", ondelete="CASCADE"))
    claim_id: Mapped[str] = mapped_column(String(64))  # <респондент>_T<реплика>_A<номер>
    turn_index: Mapped[int] = mapped_column(Integer)
    claim_text: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str] = mapped_column(Text)
    quote_ok: Mapped[bool] = mapped_column(Boolean, default=True)  # шаг 6: цитата дословно есть в реплике
    subject: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(16))
    question_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)


class Pair(Base):
    """Метка пары «утверждение × компонент» (шаг 5). Хранятся только S/C/RI — отсутствие пары = U."""
    __tablename__ = "pairs"
    __table_args__ = (UniqueConstraint("claim_pk", "component_pk"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_pk: Mapped[int] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    component_pk: Mapped[int] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(4))  # S | C | RI
    rationale: Mapped[str] = mapped_column(Text, default="")


class LlmCall(Created, Base):
    """Журнал вызовов LLM: шаг, модель, токены, время — для учёта расхода и разбора ошибок."""
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interview_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    step: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(100))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    seconds: Mapped[float] = mapped_column(Float, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
