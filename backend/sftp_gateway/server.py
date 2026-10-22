"""
Запуск SSH-сервера шлюза (раздел 19.3, 20.5 ТЗ): разрешена только подсистема
SFTP. Shell, exec, scp, PTY, проброс портов, агента и X11 отклоняются —
`process_factory` не задан, а `SSHServer` по умолчанию отказывает в
пробросе.

Перед стартом шлюз проверяет подключение к БД своей ролью: без неё не
пройдёт ни один вход, поэтому ошибка конфигурации (например, не задан
`SFTP_DB_PASSWORD`) должна остановить сервис, а не прятаться за открытым портом.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncssh
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app_logging.config import get_logger
from sftp_gateway.auth import ConnectionLimiter, GatewayServer
from sftp_gateway.config import LOGGER_NAME, LOGIN_TIMEOUT_SECONDS
from sftp_gateway.filesystem import TaskSftpServer

if TYPE_CHECKING:
    from asyncssh import SSHServerChannel

    from sftp_gateway.config import GatewayConfig, SessionFactory


logger = get_logger(LOGGER_NAME)

_PING_SQL = "SELECT 1"
_DATABASE_HINT = "проверьте SFTP_DB_PASSWORD в .env и перезапустите backend"


async def check_database(session_factory: SessionFactory) -> None:
    try:
        async with session_factory() as db_session:
            await db_session.execute(sa.text(_PING_SQL))
    except (SQLAlchemyError, OSError) as exc:
        logger.error(
            "sftp_gateway_database_unavailable",
            hint=_DATABASE_HINT,
            error=repr(exc),
        )
        raise


async def start_server(
    *,
    config: GatewayConfig,
    session_factory: SessionFactory,
    host_key: asyncssh.SSHKey,
    host: str = "",
    limiter: ConnectionLimiter | None = None,
) -> asyncssh.SSHAcceptor:
    connection_limiter = limiter or ConnectionLimiter()

    def server_factory() -> GatewayServer:
        return GatewayServer(session_factory=session_factory, limiter=connection_limiter)

    def sftp_factory(chan: SSHServerChannel[bytes]) -> TaskSftpServer:
        owner = chan.get_connection().get_owner()
        assert isinstance(owner, GatewayServer)
        assert owner.login is not None
        return TaskSftpServer(
            chan,
            login=owner.login,
            session_factory=session_factory,
            config=config,
        )

    config.user_files_root.mkdir(parents=True, exist_ok=True)
    return await asyncssh.create_server(
        server_factory,
        host,
        config.port,
        server_host_keys=[host_key],
        sftp_factory=sftp_factory,
        allow_scp=False,
        allow_pty=False,
        agent_forwarding=False,
        x11_forwarding=False,
        login_timeout=LOGIN_TIMEOUT_SECONDS,
    )
