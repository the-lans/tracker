"""
Статусы задачи до запуска, очередь пользователя и ночное окно (разделы 3.1, 14.4).

Только добавление (раздел 20.6): прежняя версия новых столбцов не читает, а
задачи в новых статусах откат переводит в `new` до перехода на прежний код
(`deploy/install.sh`).
"""

from alembic import op

revision = "a3f9d2c71e58"
down_revision = "e6b8c20d1749"
branch_labels = None
depends_on = None

_PRE_LAUNCH_STATUSES = ("refining", "defined", "ready", "night_worker")


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE нельзя использовать в той же транзакции,
    # где новое значение уже читается — выполняется отдельно, в autocommit.
    with op.get_context().autocommit_block():
        previous = "new"
        for status in _PRE_LAUNCH_STATUSES:
            op.execute(
                f"ALTER TYPE task_status ADD VALUE IF NOT EXISTS '{status}' AFTER '{previous}'",
            )
            previous = status

    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS queue_priority integer NOT NULL DEFAULT 100"
    )
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ready_at timestamptz")
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS occupies_slot boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS "
        "launched_manually boolean NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS queued_from_status task_status")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_queue_priority")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT ck_tasks_queue_priority "
        "CHECK (queue_priority BETWEEN 1 AND 1000000)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_queue "
        "ON tasks (created_by, status, queue_priority DESC, ready_at)"
    )

    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS max_parallel_tasks integer NOT NULL DEFAULT 3"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_max_parallel_tasks")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_max_parallel_tasks "
        "CHECK (max_parallel_tasks BETWEEN 1 AND 50)"
    )

    op.execute(
        "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS "
        "night_window_start time NOT NULL DEFAULT '03:15'"
    )
    op.execute(
        "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS "
        "night_window_end time NOT NULL DEFAULT '07:00'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS night_window_end")
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS night_window_start")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_max_parallel_tasks")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS max_parallel_tasks")
    op.execute("DROP INDEX IF EXISTS ix_tasks_queue")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_queue_priority")
    for column in (
        "queued_from_status",
        "launched_manually",
        "occupies_slot",
        "ready_at",
        "queue_priority",
    ):
        op.execute(f"ALTER TABLE tasks DROP COLUMN IF EXISTS {column}")
    # PostgreSQL не умеет удалять значения enum-типа: задачи в новых статусах
    # переводятся в `new`, сами значения остаются в типе.
    statuses = ", ".join(f"'{status}'" for status in _PRE_LAUNCH_STATUSES)
    op.execute(f"UPDATE tasks SET status = 'new' WHERE status::text IN ({statuses})")
