"""Сохранять контекст запроса решения отдельно от процесса SDK."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e4ac0721df52"
down_revision = "d1706a5e4fc2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("node_logs", sa.Column("decision_checkpoint", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("node_logs", "decision_checkpoint")
