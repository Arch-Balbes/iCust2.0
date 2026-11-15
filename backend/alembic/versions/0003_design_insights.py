"""Проект для интерфейса, этапы модуля коллеги, задачи проекта, стенограмма, инсайты ИГ3.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")


def upgrade() -> None:
    op.add_column("projects", sa.Column("status", sa.String(16), nullable=False, server_default="in_progress"))
    op.add_column("projects", sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("projects", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW))
    op.add_column("projects", sa.Column("selection", JSONB, nullable=False, server_default="{}"))
    op.add_column("projects", sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "design_stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("response", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("project_id", "stage"),
    )
    op.create_table(
        "project_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("project_id", "kind"),
    )
    op.create_table(
        "stenogram_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_code", sa.String(32), nullable=False),
        sa.Column("question_id", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("answers", JSONB, nullable=False),
        sa.UniqueConstraint("project_id", "segment_code", "question_id"),
    )
    op.create_table(
        "insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_code", sa.String(32), nullable=False),
        sa.Column("insight_code", sa.String(64), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("comments", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_insights_project", "insights", ["project_id", "segment_code"])


def downgrade() -> None:
    op.drop_index("ix_insights_project", "insights")
    for t in ("insights", "stenogram_rows", "project_jobs", "design_stages"):
        op.drop_table(t)
    for c in ("locked", "selection", "updated_at", "pinned", "status"):
        op.drop_column("projects", c)
