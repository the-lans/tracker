"""
Доступ к GitLab API — в учётных данных Git (раздел 3.1, 16.2).

Прежняя общая настройка (`system_settings.gitlab_url`, `gitlab_token_encrypted`)
переносится в учётные данные с тем же хостом — ровно их репозитории она и
опрашивала. Столбцы `system_settings` остаются до следующего релиза: откат на
прежнюю версию читает их (раздел 20.6).
"""

from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

revision = "f2c7a9d4e815"
down_revision = "e6b8c20d1749"
branch_labels = None
depends_on = None


def _transfer_system_setting() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT gitlab_url, gitlab_token_encrypted FROM system_settings LIMIT 1"),
    ).one_or_none()
    if row is None or not row.gitlab_url or not row.gitlab_token_encrypted:
        return
    host = (urlsplit(row.gitlab_url).hostname or "").lower()
    if not host:
        return
    url = row.gitlab_url.rstrip("/")
    bind.execute(
        sa.text(
            "UPDATE git_credentials SET gitlab_api_enabled = true, "
            "gitlab_api_token_encrypted = :token, gitlab_api_url = :url "
            "WHERE lower(git_credentials.host) = :host",
        ),
        {
            "token": row.gitlab_token_encrypted,
            # Адрес по умолчанию — `https://<host>`, хранить его незачем.
            "url": None if url == f"https://{host}" else url,
            "host": host,
        },
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE git_credentials ADD COLUMN IF NOT EXISTS "
        "gitlab_api_enabled boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE git_credentials ADD COLUMN IF NOT EXISTS gitlab_api_token_encrypted text"
    )
    op.execute("ALTER TABLE git_credentials ADD COLUMN IF NOT EXISTS gitlab_api_url varchar")
    _transfer_system_setting()


def downgrade() -> None:
    op.execute("ALTER TABLE git_credentials DROP COLUMN IF EXISTS gitlab_api_url")
    op.execute("ALTER TABLE git_credentials DROP COLUMN IF EXISTS gitlab_api_token_encrypted")
    op.execute("ALTER TABLE git_credentials DROP COLUMN IF EXISTS gitlab_api_enabled")
