"""add llm_accounts.created_by, unique claude_config_dir, nullable periodic_tasks.updated_by

Revision ID: f3b8d1c6a920
Revises: e5a2c9d47b13
Create Date: 2026-10-21 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f3b8d1c6a920'
down_revision: Union[str, Sequence[str], None] = 'e5a2c9d47b13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Решение №17 плана, как и №16: аккаунтам без владельца назначается первый
# администратор (при его отсутствии — первый пользователь).
_FIRST_OWNER_SQL = """
    (SELECT id FROM users
     ORDER BY (role = 'admin') DESC, created_at, id
     LIMIT 1)
"""


def _fail_on_unmigratable_accounts() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM users) AND EXISTS (SELECT 1 FROM llm_accounts) THEN
                RAISE EXCEPTION
                    'Нет ни одного пользователя, которому можно назначить LLM-аккаунты';
            END IF;
            IF EXISTS (
                SELECT 1 FROM llm_accounts GROUP BY claude_config_dir HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'У нескольких LLM-аккаунтов один claude_config_dir — '
                    'исправьте пути до миграции (раздел 19.5 ТЗ)';
            END IF;
        END $$;
        """,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE llm_accounts ADD COLUMN IF NOT EXISTS created_by UUID")
    _fail_on_unmigratable_accounts()
    op.execute(f"UPDATE llm_accounts SET created_by = {_FIRST_OWNER_SQL} WHERE created_by IS NULL")
    op.execute("ALTER TABLE llm_accounts ALTER COLUMN created_by SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'llm_accounts_created_by_fkey'
            ) THEN
                ALTER TABLE llm_accounts ADD CONSTRAINT llm_accounts_created_by_fkey
                    FOREIGN KEY (created_by) REFERENCES users (id);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'llm_accounts_claude_config_dir_key'
            ) THEN
                ALTER TABLE llm_accounts ADD CONSTRAINT llm_accounts_claude_config_dir_key
                    UNIQUE (claude_config_dir);
            END IF;
        END $$;
        """,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_llm_accounts_created_by ON llm_accounts (created_by)",
    )
    # Раздел 20.2 п. 8: записи periodic_tasks создаются при установке, до
    # первого входа администратора.
    op.execute("ALTER TABLE periodic_tasks ALTER COLUMN updated_by DROP NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        f"UPDATE periodic_tasks SET updated_by = {_FIRST_OWNER_SQL} WHERE updated_by IS NULL",
    )
    op.execute("ALTER TABLE periodic_tasks ALTER COLUMN updated_by SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_llm_accounts_created_by")
    op.execute(
        "ALTER TABLE llm_accounts DROP CONSTRAINT IF EXISTS llm_accounts_claude_config_dir_key",
    )
    op.execute("ALTER TABLE llm_accounts DROP CONSTRAINT IF EXISTS llm_accounts_created_by_fkey")
    op.execute("ALTER TABLE llm_accounts DROP COLUMN IF EXISTS created_by")
