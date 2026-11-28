"""Модель CI-агентов в профиле пользователя."""

import sqlalchemy as sa
from alembic import op

revision = "b203c405d607"
down_revision = "a102b304c506"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("ci_agent_model", sa.String(200), nullable=False, server_default="gpt-6-luna"),
    )


def downgrade() -> None:
    op.drop_column("users", "ci_agent_model")
