"""
Категории задач (раздел 15.7): таблицы `task_categories`,
`task_category_library_prompts` и `tasks.category_id`.

Только добавление (раздел 20.6): прежняя версия новых таблиц и столбца не
читает.
"""

from alembic import op

revision = "d8a3f6c1b742"
down_revision = "d2b7f4a9c613"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_categories (
            id uuid PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            name varchar NOT NULL,
            pipeline_id uuid REFERENCES pipelines (id) ON DELETE SET NULL,
            auto_accept_plan boolean NOT NULL DEFAULT false,
            queue_priority integer NOT NULL DEFAULT 100,
            occupies_slot boolean NOT NULL DEFAULT false,
            created_by uuid NOT NULL REFERENCES users (id),
            CONSTRAINT uq_task_categories_owner_name UNIQUE (created_by, name),
            CONSTRAINT ck_task_categories_queue_priority
                CHECK (queue_priority BETWEEN 1 AND 1000000)
        )
        """,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_categories_created_by "
        "ON task_categories (created_by)",
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_category_library_prompts (
            category_id uuid NOT NULL REFERENCES task_categories (id) ON DELETE CASCADE,
            node_id uuid NOT NULL REFERENCES nodes (id) ON DELETE CASCADE,
            PRIMARY KEY (category_id, node_id)
        )
        """,
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS category_id uuid "
        "REFERENCES task_categories (id) ON DELETE SET NULL",
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_category_id ON tasks (category_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_category_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS category_id")
    op.execute("DROP TABLE IF EXISTS task_category_library_prompts")
    op.execute("DROP TABLE IF EXISTS task_categories")
