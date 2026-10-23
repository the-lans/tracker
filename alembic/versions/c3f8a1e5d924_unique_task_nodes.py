"""task_nodes: a node appears in a task snapshot at most once

Revision ID: c3f8a1e5d924
Revises: b9e1d4f7a2c6
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3f8a1e5d924'
down_revision: Union[str, Sequence[str], None] = 'b9e1d4f7a2c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Повторная привязка пайплайна раньше добавляла снимок поверх прежнего:
    # из дублей остаётся самая ранняя запись (на `task_nodes` никто не ссылается).
    op.execute(
        """
        DELETE FROM task_nodes
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY task_id, node_id ORDER BY created_at, id
                ) AS position
                FROM task_nodes
            ) AS ranked
            WHERE position > 1
        )
        """,
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_nodes_task_id_node_id "
        "ON task_nodes (task_id, node_id)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS uq_task_nodes_task_id_node_id")
