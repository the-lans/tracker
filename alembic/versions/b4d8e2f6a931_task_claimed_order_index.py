"""
Состав нод запущенной задачи (раздел 13.2): `tasks.claimed_order_index` — нода,
выбранная оркестратором для запуска, но ещё без записи `node_logs`.

Только добавление столбца (раздел 20.6): прежняя версия его не читает.
"""

from alembic import op

revision = "b4d8e2f6a931"
down_revision = "a7e2c9d4b185"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS claimed_order_index integer")


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS claimed_order_index")
