"""
Запуск SSH-сервера шлюза (раздел 19.3, 20.5 ТЗ): разрешена только подсистема
SFTP. Shell, exec, scp, PTY, проброс портов, агента и X11 отклоняются —
`process_factory` не задан, а `SSHServer` по умолчанию отказывает в
пробросе.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncssh

from sftp_gateway.auth import ConnectionLimiter, GatewayServer
from sftp_gateway.config import LOGIN_TIMEOUT_SECONDS
from sftp_gateway.filesystem import TaskSftpServer

if TYPE_CHECKING:
    from asyncssh import SSHServerChannel

    from sftp_gateway.config import GatewayConfig, SessionFactory


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
        assert owner.user_id is not None
        return TaskSftpServer(
            chan,
            user_id=owner.user_id,
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
