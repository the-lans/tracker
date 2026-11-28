"""Состояние реализации принятого плана внутри ноды."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "c304d506e708"
down_revision = "b203c405d607"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("node_logs", sa.Column("plan_execution", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("node_logs", "plan_execution")
