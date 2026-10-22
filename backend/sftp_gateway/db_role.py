"""
Роль Postgres SFTP-шлюза с минимальными правами (раздел 20.5 ТЗ).

Шлюз открыт в интернет, поэтому подключается к БД не владельцем схемы, а
ролью, которая читает только нужное для входа и видимости задач:
`users` целиком (сущность пользователя), из `tasks` — только код и автора;
обновляет одну колонку `users.ssh_key_last_used_at` и добавляет записи
`app_logs` (а `id`/`created_at` читает — их возвращает INSERT ... RETURNING).
Секреты (`env_variables`, ключи репозиториев, MCP) ей недоступны.

Запускается из `docker-entrypoint.sh` backend после миграций при каждом
старте, а не миграцией: `pg_dump` не переносит роли, и после переноса на
новый сервер (`install.sh --restore`) миграции уже применены.
"""

from __future__ import annotations

import asyncio
import os

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app_logging.config import configure_logging, get_logger

logger = get_logger("sftp_db_role")

ROLE_NAME = "tracker_sftp"
_PASSWORD_ENV_VAR = "SFTP_DB_PASSWORD"
# backend и реплики worker стартуют с одним entrypoint: одновременные GRANT
# одной роли падают с "tuple concurrently updated", поэтому — по очереди.
_ADVISORY_LOCK_ID = 7_318_042

_CREATE_ROLE_SQL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
        CREATE ROLE {ROLE_NAME} LOGIN;
    END IF;
END
$$
"""
_GRANTS_SQL = (
    f"GRANT USAGE ON SCHEMA public TO {ROLE_NAME}",
    f"GRANT SELECT ON users TO {ROLE_NAME}",
    f"GRANT UPDATE (ssh_key_last_used_at) ON users TO {ROLE_NAME}",
    f"GRANT SELECT (code, created_by) ON tasks TO {ROLE_NAME}",
    f"GRANT INSERT ON app_logs TO {ROLE_NAME}",
    f"GRANT SELECT (id, created_at) ON app_logs TO {ROLE_NAME}",
)


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


async def ensure_sftp_db_role(database_url: str, password: str) -> None:
    """Идемпотентно: создаёт роль, задаёт пароль и права."""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": _ADVISORY_LOCK_ID},
            )
            await connection.execute(sa.text(_CREATE_ROLE_SQL))
            # Пароль в ALTER ROLE не передаётся параметром — только литералом;
            # exec_driver_sql — чтобы ":" в пароле не стал именем параметра.
            password_sql = f"ALTER ROLE {ROLE_NAME} WITH LOGIN PASSWORD {_quote_literal(password)}"
            await connection.exec_driver_sql(password_sql)
            for grant in _GRANTS_SQL:
                await connection.execute(sa.text(grant))
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging()
    password = os.environ.get(_PASSWORD_ENV_VAR)
    if not password:
        logger.warning("sftp_db_role_skipped", reason=f"{_PASSWORD_ENV_VAR} не задан")
        return
    asyncio.run(ensure_sftp_db_role(os.environ["DATABASE_URL"], password))
    logger.info("sftp_db_role_ready", role=ROLE_NAME)


if __name__ == "__main__":
    main()
