"""Закрытие приёма ручных запросов перед завершением задачи."""

from alembic import op

revision = "e6b8c20d1749"
down_revision = "d7a41e9b5206"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS "
        "manual_requests_closed boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS manual_requests_closed")
