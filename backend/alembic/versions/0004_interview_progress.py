"""Прогресс обработки интервью для индикатора на экране 08.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("interviews", sa.Column("stage_progress", sa.Float(), nullable=False, server_default="0"))
    op.add_column("interviews", sa.Column("stage_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("interviews", "stage_started_at")
    op.drop_column("interviews", "stage_progress")
