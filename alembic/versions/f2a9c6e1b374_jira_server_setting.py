"""Jira server address moves from users to system_settings

Revision ID: f2a9c6e1b374
Revises: e7c4b2a9d018
Create Date: 2026-10-23 19:00:00.000000

Адрес Jira задаёт администратор (раздел 15.6): сервер, к которому обращается
backend, пользователь не выбирает. Сохранённый ранее личный адрес переносится
в настройки, если там ещё пусто; личные email и токен остаются у пользователя.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f2a9c6e1b374'
down_revision: Union[str, Sequence[str], None] = 'e7c4b2a9d018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS jira_url VARCHAR")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'jira_url'
            ) THEN
                UPDATE system_settings
                SET jira_url = (
                    SELECT users.jira_url FROM users
                    WHERE users.jira_url IS NOT NULL
                    GROUP BY users.jira_url
                    ORDER BY count(*) DESC, users.jira_url
                    LIMIT 1
                )
                WHERE system_settings.jira_url IS NULL;
            END IF;
        END $$;
        """,
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS jira_url")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS jira_url VARCHAR")
    op.execute(
        """
        UPDATE users SET jira_url = (SELECT system_settings.jira_url FROM system_settings LIMIT 1)
        WHERE users.jira_token_encrypted IS NOT NULL
        """,
    )
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS jira_url")
