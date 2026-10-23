"""move GitLab URL and token from env_variables to system_settings

Revision ID: b9e1d4f7a2c6
Revises: a7c4e2f9b318
Create Date: 2026-10-23 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b9e1d4f7a2c6'
down_revision: Union[str, Sequence[str], None] = 'a7c4e2f9b318'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_URL_KEY = "GITLAB_URL"
_TOKEN_KEY = "GITLAB_TOKEN"


def _global_values() -> dict[str, str]:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT key, value_encrypted FROM env_variables "
            "WHERE scope = 'global' AND key IN (:url_key, :token_key)",
        ),
        {"url_key": _URL_KEY, "token_key": _TOKEN_KEY},
    )
    return {key: value for key, value in rows}


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS gitlab_url VARCHAR")
    op.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS gitlab_token_encrypted TEXT")
    values = _global_values()
    if not values:
        return
    # Адрес хранится открыто: его расшифровывает тот же ключ, что и приложение.
    from services.crypto import decrypt

    url = decrypt(values[_URL_KEY]) if _URL_KEY in values else None
    op.get_bind().execute(
        sa.text(
            "UPDATE system_settings SET gitlab_url = :url, gitlab_token_encrypted = :token",
        ),
        {"url": url, "token": values.get(_TOKEN_KEY)},
    )
    op.get_bind().execute(
        sa.text(
            "DELETE FROM env_variables WHERE scope = 'global' AND key IN (:url_key, :token_key)",
        ),
        {"url_key": _URL_KEY, "token_key": _TOKEN_KEY},
    )


def downgrade() -> None:
    """Downgrade schema."""
    row = op.get_bind().execute(
        sa.text("SELECT gitlab_url, gitlab_token_encrypted FROM system_settings LIMIT 1"),
    ).first()
    if row is not None and (row.gitlab_url or row.gitlab_token_encrypted):
        from services.crypto import encrypt

        insert = sa.text(
            "INSERT INTO env_variables (id, key, value_encrypted, is_secret, scope) "
            "VALUES (gen_random_uuid(), :key, :value, :is_secret, 'global')",
        )
        if row.gitlab_url:
            op.get_bind().execute(
                insert,
                {"key": _URL_KEY, "value": encrypt(row.gitlab_url), "is_secret": False},
            )
        if row.gitlab_token_encrypted:
            op.get_bind().execute(
                insert,
                {"key": _TOKEN_KEY, "value": row.gitlab_token_encrypted, "is_secret": True},
            )
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS gitlab_token_encrypted")
    op.execute("ALTER TABLE system_settings DROP COLUMN IF EXISTS gitlab_url")
