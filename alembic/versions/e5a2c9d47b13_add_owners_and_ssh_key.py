"""add created_by to pipelines, nodes, templates and users.ssh_public_key

Revision ID: e5a2c9d47b13
Revises: d81e5b3c7a26
Create Date: 2026-10-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5a2c9d47b13'
down_revision: Union[str, Sequence[str], None] = 'd81e5b3c7a26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OWNED_TABLES = ("pipelines", "nodes", "templates")

# Решение №16 плана: записям без автора назначается первый администратор
# (при его отсутствии — первый пользователь).
_FIRST_OWNER_SQL = """
    (SELECT id FROM users
     ORDER BY (role = 'admin') DESC, created_at, id
     LIMIT 1)
"""


def _fail_if_rows_without_users() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM users) AND (
                EXISTS (SELECT 1 FROM pipelines)
                OR EXISTS (SELECT 1 FROM nodes)
                OR EXISTS (SELECT 1 FROM templates)
            ) THEN
                RAISE EXCEPTION
                    'Нет ни одного пользователя, которому можно назначить '
                    'существующие пайплайны, ноды и шаблоны';
            END IF;
        END $$;
        """,
    )


def upgrade() -> None:
    """Upgrade schema."""
    for table in _OWNED_TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS created_by UUID")

    _fail_if_rows_without_users()
    op.execute(f"UPDATE pipelines SET created_by = {_FIRST_OWNER_SQL} WHERE created_by IS NULL")
    op.execute(f"UPDATE templates SET created_by = {_FIRST_OWNER_SQL} WHERE created_by IS NULL")
    # Нода пайплайна принадлежит автору пайплайна (services/access.py).
    op.execute(
        """
        UPDATE nodes SET created_by = pipelines.created_by
        FROM pipelines
        WHERE nodes.pipeline_id = pipelines.id AND nodes.created_by IS NULL
        """,
    )
    op.execute(f"UPDATE nodes SET created_by = {_FIRST_OWNER_SQL} WHERE created_by IS NULL")

    for table in _OWNED_TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_by SET NOT NULL")
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{table}_created_by_fkey'
                ) THEN
                    ALTER TABLE {table} ADD CONSTRAINT {table}_created_by_fkey
                        FOREIGN KEY (created_by) REFERENCES users (id);
                END IF;
            END $$;
            """,
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_created_by ON {table} (created_by)",
        )

    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ssh_public_key TEXT")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS ssh_public_key")
    for table in _OWNED_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_created_by")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_created_by_fkey")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS created_by")
