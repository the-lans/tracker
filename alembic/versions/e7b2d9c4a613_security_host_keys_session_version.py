"""
Информационная безопасность (разделы 3.1, 19.1, 19.3):
`git_credentials.ssh_known_hosts` — ключи Git-сервера, проверяемые при работе
по SSH (запоминаются при первом подключении), и `users.session_version` —
версия сессий пользователя: «Выйти на всех устройствах» её увеличивает, и
выданные раньше токены перестают действовать.

Только добавление (раздел 20.6): прежняя версия столбцы не читает; токены без
версии считаются версией 0, поэтому после обновления никого не выкидывает.
"""

from alembic import op

revision = "e7b2d9c4a613"
down_revision = "c1d4e7a2b958"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE git_credentials ADD COLUMN IF NOT EXISTS ssh_known_hosts text")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version integer NOT NULL DEFAULT 0",
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS session_version")
    op.execute("ALTER TABLE git_credentials DROP COLUMN IF EXISTS ssh_known_hosts")
