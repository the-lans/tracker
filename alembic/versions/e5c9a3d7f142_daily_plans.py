"""
«Дейли» (разделы 3.1, 15.8, 19.8): отметки задач по дням, события дня, планы
на день, шаблон плана, подключение к Google Calendar и начало дня в системных
настройках.

Только добавление (раздел 20.6): прежняя версия новых таблиц и столбца не
читает, а периодическую синхронизацию календаря откат удаляет
(`deploy/install.sh`).
"""

from alembic import op

revision = "e5c9a3d7f142"
down_revision = "b7d4e2a9c615"
branch_labels = None
depends_on = None

_ENUMS = {
    "daily_event_source": "('manual', 'google')",
    "google_calendar_status": "('connected', 'needs_reauth')",
}
_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS task_day_marks (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL DEFAULT now(),
        user_id uuid NOT NULL REFERENCES users (id),
        task_id uuid NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
        day date NOT NULL,
        CONSTRAINT uq_task_day_marks_user_task_day UNIQUE (user_id, task_id, day)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_events (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        user_id uuid NOT NULL REFERENCES users (id),
        source daily_event_source NOT NULL,
        day date NOT NULL,
        end_day date NOT NULL,
        starts_at timestamptz,
        ends_at timestamptz,
        title varchar NOT NULL,
        notes text,
        hidden boolean NOT NULL DEFAULT false,
        calendar_id varchar,
        external_id varchar,
        CONSTRAINT ck_daily_events_end_day CHECK (end_day >= day)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_plans (
        id uuid PRIMARY KEY,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        user_id uuid NOT NULL REFERENCES users (id),
        day date NOT NULL,
        content text NOT NULL,
        CONSTRAINT uq_daily_plans_user_day UNIQUE (user_id, day)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_plan_templates (
        user_id uuid PRIMARY KEY REFERENCES users (id),
        content text NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS google_calendar_connections (
        user_id uuid PRIMARY KEY REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        google_email varchar NOT NULL,
        refresh_token_encrypted text NOT NULL,
        calendar_ids jsonb NOT NULL DEFAULT '["primary"]'::jsonb,
        status google_calendar_status NOT NULL DEFAULT 'connected',
        last_synced_at timestamptz,
        last_error text
    )
    """,
)
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_task_day_marks_user_day ON task_day_marks (user_id, day)",
    "CREATE INDEX IF NOT EXISTS ix_daily_events_user_day ON daily_events (user_id, day)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_events_google_event "
    "ON daily_events (user_id, calendar_id, external_id) WHERE source = 'google'",
)
_DROPPED_TABLES = (
    "google_calendar_connections",
    "daily_plan_templates",
    "daily_plans",
    "daily_events",
    "task_day_marks",
)


def upgrade() -> None:
    for name, values in _ENUMS.items():
        op.execute(
            f"""
            DO $$ BEGIN
                CREATE TYPE {name} AS ENUM {values};
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
            """,
        )
    for statement in (*_TABLES, *_INDEXES):
        op.execute(statement)
    op.execute(
        "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS day_start_time time "
        "NOT NULL DEFAULT '08:00'",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS day_start_time")
    for table in _DROPPED_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for name in _ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")
