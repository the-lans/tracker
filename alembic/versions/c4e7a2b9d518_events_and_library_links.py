"""
Лента событий (раздел 18.4): таблица `events`. Нода пайплайна со ссылкой на
промт библиотеки (раздел 7.6): `nodes.library_node_id`, `nodes.library_arguments`.
Индекс `app_logs(created_at)` для мониторинга (раздел 15.5).

Только добавление (раздел 20.6): прежняя версия новых столбцов и таблицы не
читает.
"""

from alembic import op

revision = "c4e7a2b9d518"
down_revision = "b7d3e91a4c52"
branch_labels = None
depends_on = None

_ENUM_TYPES = (
    ("event_audience", "'user', 'admins'"),
    ("event_category", "'task', 'llm_account', 'periodic', 'backup', 'profile'"),
)
_NODE_COLUMNS = (
    "library_node_id uuid REFERENCES nodes (id)",
    "library_arguments varchar",
)
_NODE_LIBRARY_CHECK = "ck_nodes_library_node_id_pipeline_only"


def _create_enum(type_name: str, values: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE {type_name} AS ENUM ({values});
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """,
    )


def upgrade() -> None:
    for type_name, values in _ENUM_TYPES:
        _create_enum(type_name, values)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id uuid PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT now(),
            audience event_audience NOT NULL,
            user_id uuid REFERENCES users (id),
            category event_category NOT NULL,
            event_type varchar NOT NULL,
            title varchar NOT NULL,
            body text NOT NULL,
            task_id uuid REFERENCES tasks (id) ON DELETE SET NULL,
            CONSTRAINT ck_events_audience_user_id
                CHECK ((audience = 'user') = (user_id IS NOT NULL))
        )
        """,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_events_user_id_created_at "
        "ON events (user_id, created_at DESC)",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_events_audience_created_at "
        "ON events (audience, created_at DESC)",
    )
    for column in _NODE_COLUMNS:
        op.execute(f"ALTER TABLE nodes ADD COLUMN IF NOT EXISTS {column}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_nodes_library_node_id ON nodes (library_node_id)")
    op.execute(
        f"""
        DO $$ BEGIN
            ALTER TABLE nodes ADD CONSTRAINT {_NODE_LIBRARY_CHECK}
                CHECK (library_node_id IS NULL OR pipeline_id IS NOT NULL);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_app_logs_created_at ON app_logs (created_at DESC)",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_app_logs_created_at")
    op.execute(f"ALTER TABLE nodes DROP CONSTRAINT IF EXISTS {_NODE_LIBRARY_CHECK}")
    op.execute("DROP INDEX IF EXISTS ix_nodes_library_node_id")
    for column in reversed(_NODE_COLUMNS):
        op.execute(f"ALTER TABLE nodes DROP COLUMN IF EXISTS {column.split()[0]}")
    op.execute("DROP TABLE IF EXISTS events")
    for type_name, _ in reversed(_ENUM_TYPES):
        op.execute(f"DROP TYPE IF EXISTS {type_name}")
