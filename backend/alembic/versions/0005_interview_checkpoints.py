"""Контрольные точки обработки интервью: утверждения сохранены, готовые пакеты шага 5.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

BATCH5 = 15  # как app.ig1.llm.BATCH5 на момент миграции


def upgrade() -> None:
    op.add_column("interviews", sa.Column("claims_ready", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("interviews", sa.Column("step5_done", postgresql.JSONB(), nullable=False, server_default="[]"))
    # Уже обработанные записи: утверждения готовы, все пакеты шага 5 выполнены — повтор не должен их пересчитывать
    op.execute("""
        update interviews i set claims_ready = true,
               step5_done = coalesce((select jsonb_agg(g) from generate_series(
                   0, ceil((select count(*) from claims c where c.interview_id = i.id) / 15.0)::int - 1) g), '[]')
        where i.status = 'processed'
    """)  # 15 = BATCH5


def downgrade() -> None:
    op.drop_column("interviews", "step5_done")
    op.drop_column("interviews", "claims_ready")
