"""
Сроки хранения данных (разделы 6.4, 14.3, 17.2): отметки об удалении истории
сессии и артефактов архивной задачи, срок хранения артефактов у пользователя
и срок журнала `app_logs` в системных настройках (0 — бессрочно).

Только добавление (раздел 20.6): прежняя версия новых столбцов не читает, а
периодические задачи очистки откат удаляет (`deploy/install.sh`).
"""

from alembic import op

revision = "b7d4e2a9c615"
down_revision = "f3a8c5e1d927"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS session_cleaned_at timestamptz")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS artifacts_cleaned_at timestamptz")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS artifacts_retention_days integer NOT NULL "
        "DEFAULT 90 CONSTRAINT ck_users_artifacts_retention_days "
        "CHECK (artifacts_retention_days BETWEEN 0 AND 3650)"
    )
    op.execute(
        "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS app_logs_retention_days integer "
        "NOT NULL DEFAULT 30 CONSTRAINT ck_system_settings_app_logs_retention_days "
        "CHECK (app_logs_retention_days BETWEEN 0 AND 3650)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS app_logs_retention_days")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS artifacts_retention_days")
    for column in ("artifacts_cleaned_at", "session_cleaned_at"):
        op.execute(f"ALTER TABLE tasks DROP COLUMN IF EXISTS {column}")
