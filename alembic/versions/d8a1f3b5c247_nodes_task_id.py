"""nodes.task_id: custom nodes inserted into a single task

Revision ID: d8a1f3b5c247
Revises: c6d2e8f4a170
Create Date: 2026-10-25 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8a1f3b5c247'
down_revision: Union[str, Sequence[str], None] = 'c6d2e8f4a170'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "ck_nodes_is_library_item_matches_pipeline_id"
_CUSTOM_NODES = "SELECT id FROM nodes WHERE task_id IS NOT NULL"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE nodes ADD COLUMN IF NOT EXISTS task_id UUID")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'nodes_task_id_fkey') THEN
                ALTER TABLE nodes ADD CONSTRAINT nodes_task_id_fkey
                    FOREIGN KEY (task_id) REFERENCES tasks (id);
            END IF;
        END $$;
        """,
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_nodes_task_id ON nodes (task_id)")
    op.execute(f"ALTER TABLE nodes DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"""
        ALTER TABLE nodes ADD CONSTRAINT {_CONSTRAINT} CHECK (
            (is_library_item AND pipeline_id IS NULL AND task_id IS NULL)
            OR (NOT is_library_item AND num_nonnulls(pipeline_id, task_id) = 1)
        )
        """,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Прежняя схема своих нод задачи не знает: их история остаётся без ноды.
    op.execute(f"UPDATE node_logs SET node_id = NULL WHERE node_id IN ({_CUSTOM_NODES})")
    op.execute(f"DELETE FROM task_nodes WHERE node_id IN ({_CUSTOM_NODES})")
    op.execute("DELETE FROM nodes WHERE task_id IS NOT NULL")
    op.execute(f"ALTER TABLE nodes DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(
        f"""
        ALTER TABLE nodes ADD CONSTRAINT {_CONSTRAINT} CHECK (
            (is_library_item AND pipeline_id IS NULL)
            OR (NOT is_library_item AND pipeline_id IS NOT NULL)
        )
        """,
    )
    op.execute("DROP INDEX IF EXISTS ix_nodes_task_id")
    op.execute("ALTER TABLE nodes DROP CONSTRAINT IF EXISTS nodes_task_id_fkey")
    op.execute("ALTER TABLE nodes DROP COLUMN IF EXISTS task_id")
