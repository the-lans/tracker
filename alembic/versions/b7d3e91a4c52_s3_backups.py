"""
Резервное копирование в S3 (раздел 20.4): настройки хранилища и пароль
шифрования в `system_settings`, история запусков бэкапа и проверки
восстановления в `backup_runs`.

Только добавление (раздел 20.6): прежняя версия новых столбцов и таблицы не
читает.
"""

from alembic import op

revision = "b7d3e91a4c52"
down_revision = "e5b81c4d2f97"
branch_labels = None
depends_on = None

_ENUM_TYPES = (
    ("backup_run_kind", "'backup', 'verify'"),
    ("backup_run_status", "'running', 'success', 'warning', 'failed'"),
)
_SETTINGS_COLUMNS = (
    "backup_enabled boolean NOT NULL DEFAULT false",
    "backup_s3_endpoint varchar",
    "backup_s3_region varchar",
    "backup_s3_bucket varchar",
    "backup_s3_access_key varchar",
    "backup_s3_secret_key_encrypted text",
    "backup_s3_folder varchar NOT NULL DEFAULT 'Tracker'",
    "backup_retention_count integer NOT NULL DEFAULT 7",
    "backup_passphrase_encrypted text",
)
_RETENTION_CHECK = "ck_system_settings_backup_retention_count"


def upgrade() -> None:
    for type_name, values in _ENUM_TYPES:
        op.execute(
            f"""
            DO $$ BEGIN
                CREATE TYPE {type_name} AS ENUM ({values});
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
            """,
        )
    for column in _SETTINGS_COLUMNS:
        op.execute(f"ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS {column}")
    op.execute(
        f"""
        DO $$ BEGIN
            ALTER TABLE system_settings ADD CONSTRAINT {_RETENTION_CHECK}
                CHECK (backup_retention_count BETWEEN 1 AND 365);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_runs (
            id uuid PRIMARY KEY,
            kind backup_run_kind NOT NULL,
            status backup_run_status NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            object_key varchar,
            size_bytes bigint,
            sha256 varchar,
            skipped_files jsonb NOT NULL DEFAULT '[]'::jsonb,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            error_message text
        )
        """,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backup_runs_kind_started_at "
        "ON backup_runs (kind, started_at DESC)",
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backup_runs")
    op.execute(f"ALTER TABLE system_settings DROP CONSTRAINT IF EXISTS {_RETENTION_CHECK}")
    for column in reversed(_SETTINGS_COLUMNS):
        op.execute(f"ALTER TABLE system_settings DROP COLUMN IF EXISTS {column.split()[0]}")
    for type_name, _ in reversed(_ENUM_TYPES):
        op.execute(f"DROP TYPE IF EXISTS {type_name}")
