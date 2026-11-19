"""Описание задачи Jira в HTML для показа; добавление совместимо с предыдущим релизом."""

from alembic import op

revision = "b5d3e8a1c724"
down_revision = "a8f2c9d1e603"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS description_html TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS description_html")
