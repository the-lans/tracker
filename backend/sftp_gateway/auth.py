"""
Вход в SFTP-шлюз (раздел 3.1, 15.1, 17.2 ТЗ): логин — `users.os_username`,
единственный способ — публичный ключ из профиля трекера.

`validate_public_key` только отвечает, подходит ли ключ; вход состоялся
лишь после проверки подписи (`auth_completed`) — тогда отмечается дата
использования ключа и пишется запись аудита. Неудачный вход известного
пользователя пишется в `app_logs` один раз на соединение; попытки с
неизвестным логином (сканеры) — только в stdout.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import asyncssh

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from db.models.enums import AppLogLevel
from services.sftp_access import find_sftp_login, key_matches, touch_ssh_key_usage
from sftp_gateway.config import MAX_CONNECTIONS, MAX_CONNECTIONS_PER_IP, SessionFactory

if TYPE_CHECKING:
    from asyncssh import SSHKey, SSHServerConnection

logger = get_logger("sftp_gateway")

LOG_SOURCE = "sftp"
_UNKNOWN_PEER = "unknown"
# Колбэки asyncssh синхронные: запись в БД идёт фоновой задачей, ссылка на
# которую хранится до завершения (иначе её может собрать сборщик мусора).
_background_tasks: set[asyncio.Task[None]] = set()


def _in_background(coroutine: Coroutine[Any, Any, None]) -> None:
    task = asyncio.get_running_loop().create_task(coroutine)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class ConnectionLimiter:
    """Счётчик открытых соединений: всего и с одного адреса."""

    def __init__(
        self,
        *,
        per_ip: int = MAX_CONNECTIONS_PER_IP,
        total: int = MAX_CONNECTIONS,
    ) -> None:
        self._per_ip = per_ip
        self._total = total
        self._by_ip: Counter[str] = Counter()

    def acquire(self, ip: str) -> bool:
        if self._by_ip[ip] >= self._per_ip or self._by_ip.total() >= self._total:
            return False
        self._by_ip[ip] += 1
        return True

    def release(self, ip: str) -> None:
        self._by_ip[ip] -= 1
        if self._by_ip[ip] <= 0:
            del self._by_ip[ip]


class GatewayServer(asyncssh.SSHServer):
    """Одно SSH-соединение; `user_id` заполняется после успешного входа."""

    def __init__(self, *, session_factory: SessionFactory, limiter: ConnectionLimiter) -> None:
        self._session_factory = session_factory
        self._limiter = limiter
        self._peer = _UNKNOWN_PEER
        self._counted = False
        self._candidate: tuple[uuid.UUID, str] | None = None
        self._rejected_login: str | None = None
        self.user_id: uuid.UUID | None = None

    def connection_made(self, conn: SSHServerConnection) -> None:
        peer = conn.get_extra_info("peername")
        self._peer = str(peer[0]) if peer else _UNKNOWN_PEER
        self._counted = self._limiter.acquire(self._peer)
        if not self._counted:
            logger.warning("sftp_connection_limit_reached", peer=self._peer)
            conn.close()

    def connection_lost(self, exc: Exception | None) -> None:
        if self._counted:
            self._limiter.release(self._peer)
        if self.user_id is None and self._rejected_login is not None:
            self._audit_rejection(self._rejected_login)

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return False

    def kbdint_auth_supported(self) -> bool:
        return False

    def public_key_auth_supported(self) -> bool:
        return True

    async def validate_public_key(self, username: str, key: SSHKey) -> bool:
        async with self._session_factory() as db_session:
            user = await find_sftp_login(db_session, username=username)
        if user is None:
            logger.info("sftp_unknown_login", peer=self._peer, username=username)
            return False
        if not key_matches(user, key.public_data):
            self._rejected_login = username
            return False
        self._candidate = (user.id, username)
        return True

    async def _record_login(self, user_id: uuid.UUID, username: str) -> None:
        async with self._session_factory() as db_session:
            await touch_ssh_key_usage(db_session, user_id=user_id, now=datetime.now(UTC))
        logger.info("sftp_login", peer=self._peer, username=username)
        await write_app_log(
            level=AppLogLevel.INFO,
            source=LOG_SOURCE,
            message=f"Вход в SFTP-шлюз: {username}",
            context={"user_id": str(user_id), "username": username, "peer": self._peer},
        )

    def auth_completed(self) -> None:
        if self._candidate is None:
            return
        self.user_id, username = self._candidate
        _in_background(self._record_login(self.user_id, username))

    def _audit_rejection(self, username: str) -> None:
        logger.warning("sftp_login_rejected", peer=self._peer, username=username)
        _in_background(
            write_app_log(
                level=AppLogLevel.WARNING,
                source=LOG_SOURCE,
                message=f"Отказ во входе в SFTP-шлюз: {username} — ключ не подошёл или вход закрыт",
                context={"username": username, "peer": self._peer},
            ),
        )
