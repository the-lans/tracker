"""Настройки SFTP-шлюза (раздел 20.3 ТЗ)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from services.sftp_connection import host_key_path
from services.task_artifacts import resolve_user_files_root
from services.task_workspace import resolve_repos_root

LOGGER_NAME = "sftp_gateway"
# Порт внутри контейнера; наружу публикуется `SFTP_PORT` (docker-compose.yml).
LISTEN_PORT = 2222
LOGIN_TIMEOUT_SECONDS = 30
# Защита от перебора и исчерпания соединений одним адресом.
MAX_CONNECTIONS_PER_IP = 10
MAX_CONNECTIONS = 100

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    repos_root: Path
    user_files_root: Path
    host_key_path: Path
    port: int = LISTEN_PORT


def load_config() -> GatewayConfig:
    return GatewayConfig(
        repos_root=resolve_repos_root(),
        user_files_root=resolve_user_files_root(),
        host_key_path=host_key_path(),
    )
