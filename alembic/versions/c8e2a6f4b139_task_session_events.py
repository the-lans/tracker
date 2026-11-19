"""
События сессии задачи для ленты чата (раздел 15.2): сброс контекста и начало
новой сессии.

Только добавление (раздел 20.6): прежняя версия новой таблицы не читает.
"""

from alembic import op

revision = "c8e2a6f4b139"
down_revision = "b5d3e8a1c724"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE task_session_event_kind AS ENUM ('context_cleared', 'session_started');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """,
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS task_session_events (
            id uuid PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT now(),
            task_id uuid NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
            kind task_session_event_kind NOT NULL
        )
        """,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_session_events_task_id_created_at "
        "ON task_session_events (task_id, created_at)",
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS task_session_events")
    op.execute("DROP TYPE IF EXISTS task_session_event_kind")
