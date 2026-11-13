"""
Архив задач (раздел 14.2): статус `archived`, момент завершения задачи,
сроки архивации и очистки репозиториев у пользователя.

Только добавление (раздел 20.6): прежняя версия новых столбцов не читает, а
архивные задачи откат возвращает в их итоговый статус до перехода на прежний
код (`deploy/install.sh`).
"""

from alembic import op

revision = "f3a8c5e1d927"
down_revision = "d8a3f6c1b742"
branch_labels = None
depends_on = None

# Статуса `archived` прежняя версия не знает: задача возвращается в `done`/`failed`.
_RESTORE_ARCHIVED = (
    "UPDATE tasks SET status = archived_from_status "
    "WHERE status::text = 'archived'"
)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE нельзя использовать в той же транзакции,
    # где новое значение уже читается — выполняется отдельно, в autocommit.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'archived'")

    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS finished_at timestamptz")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS archived_at timestamptz")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS archived_from_status task_status")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_status_finished_at ON tasks (status, finished_at)"
    )
    # Момент завершения уже завершённых задач неизвестен — берётся последнее
    # изменение задачи, как у напоминания об очистке (раздел 16.2).
    op.execute(
        "UPDATE tasks SET finished_at = updated_at "
        "WHERE status IN ('done', 'failed') AND finished_at IS NULL"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS archive_after_days integer DEFAULT 14 "
        "CONSTRAINT ck_users_archive_after_days CHECK (archive_after_days BETWEEN 1 AND 3650)"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS cleanup_repos_after_days integer DEFAULT 30 "
        "CONSTRAINT ck_users_cleanup_repos_after_days "
        "CHECK (cleanup_repos_after_days BETWEEN 1 AND 3650)"
    )


def downgrade() -> None:
    # PostgreSQL не умеет удалять значения enum-типа: архивные задачи уходят в
    # итоговый статус (как откат в `deploy/install.sh`), значение остаётся в типе.
    op.execute(_RESTORE_ARCHIVED)
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS cleanup_repos_after_days")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS archive_after_days")
    op.execute("DROP INDEX IF EXISTS ix_tasks_status_finished_at")
    for column in ("archived_from_status", "archived_at", "finished_at"):
        op.execute(f"ALTER TABLE tasks DROP COLUMN IF EXISTS {column}")
