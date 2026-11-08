"""Пользовательские команды библиотеки и снимки вызовов в очереди."""

from alembic import op

revision = "d7a41e9b5206"
down_revision = "c9e2f6a81034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, columns in {
        "nodes": {
            "slash_name": "varchar(64)",
            "argument_hint": "varchar(200)",
            "revision": "integer NOT NULL DEFAULT 1",
        },
        "task_manual_request_queue": {
            "command_name": "varchar(64)",
            "command_revision": "integer",
            "command_snapshot_encrypted": "text",
            "client_request_id": "uuid",
        },
        "node_logs": {"command_name": "varchar(64)", "command_revision": "integer"},
    }.items():
        for column, definition in columns.items():
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
            )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_nodes_owner_slash_name "
        "ON nodes (created_by, slash_name) WHERE slash_name IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_command_client "
        "ON task_manual_request_queue (task_id, requested_by, client_request_id) "
        "WHERE client_request_id IS NOT NULL"
    )
    constraints = {
        "ck_nodes_slash_name": (
            "nodes",
            "slash_name IS NULL OR (is_library_item AND node_type "
            "IN ('plain_prompt', 'script') AND slash_name ~ '^[a-z][a-z0-9_-]{0,63}$')",
        ),
        "ck_manual_command_snapshot": (
            "task_manual_request_queue",
            "(command_name IS NULL AND command_revision IS NULL AND command_snapshot_encrypted IS NULL "
            "AND client_request_id IS NULL) OR (command_name IS NOT NULL AND command_revision IS NOT NULL "
            "AND command_snapshot_encrypted IS NOT NULL AND client_request_id IS NOT NULL "
            "AND request_type = 'library_prompt')",
        ),
    }
    for name, (table, condition) in constraints.items():
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_constraint WHERE conname='{name}' "
            f"AND conrelid='{table}'::regclass) THEN ALTER TABLE {table} ADD CONSTRAINT "
            f"{name} CHECK ({condition}); END IF; END $$"
        )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE task_manual_request_queue DROP CONSTRAINT IF EXISTS ck_manual_command_snapshot"
    )
    op.execute("ALTER TABLE nodes DROP CONSTRAINT IF EXISTS ck_nodes_slash_name")
    op.execute("DROP INDEX IF EXISTS uq_manual_command_client")
    op.execute("DROP INDEX IF EXISTS uq_nodes_owner_slash_name")
    # Принятые команды нельзя превращать в запуски текущей, изменённой версии ноды.
    op.execute(
        "UPDATE task_manual_request_queue SET status='cancelled' "
        "WHERE command_name IS NOT NULL AND status='queued'"
    )
    for table, columns in {
        "nodes": ("slash_name", "argument_hint", "revision"),
        "task_manual_request_queue": (
            "command_name",
            "command_revision",
            "command_snapshot_encrypted",
            "client_request_id",
        ),
        "node_logs": ("command_name", "command_revision"),
    }.items():
        for column in columns:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
