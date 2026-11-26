"""Оставить одну привязку библиотечного промта на задачу."""

from alembic import op

revision = "d1706a5e4fc2"
down_revision = "b4d8e2f6a931"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_task_library_prompts_task_node"


def upgrade() -> None:
    op.execute("LOCK TABLE task_library_prompts IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        WITH earliest AS (
            SELECT DISTINCT ON (task_id, node_id) id, task_id, node_id
            FROM task_library_prompts
            ORDER BY task_id, node_id, added_at, id
        ),
        latest_run AS (
            SELECT DISTINCT ON (task_id, node_id)
                task_id, node_id, last_run_at, last_run_status
            FROM task_library_prompts
            WHERE last_run_at IS NOT NULL
            ORDER BY task_id, node_id, last_run_at DESC, added_at DESC, id DESC
        )
        UPDATE task_library_prompts
        SET last_run_at = latest_run.last_run_at, last_run_status = latest_run.last_run_status
        FROM earliest JOIN latest_run USING (task_id, node_id)
        WHERE task_library_prompts.id = earliest.id
          AND (
              task_library_prompts.last_run_at IS NULL
              OR task_library_prompts.last_run_at < latest_run.last_run_at
          )
    """)
    op.execute("""
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY task_id, node_id ORDER BY added_at, id
            ) AS position
            FROM task_library_prompts
        )
        DELETE FROM task_library_prompts
        WHERE id IN (SELECT id FROM ranked WHERE position > 1)
    """)
    op.create_unique_constraint(_CONSTRAINT, "task_library_prompts", ["task_id", "node_id"])


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "task_library_prompts", type_="unique")
