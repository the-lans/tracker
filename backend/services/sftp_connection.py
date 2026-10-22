"""
Данные подключения к SFTP-шлюзу (раздел 15.1, 20.3 ТЗ, решение №18 плана).

Ключ хоста создаёт сам шлюз в volume `sftp_host_keys`; backend видит этот
volume только для чтения и показывает отпечаток в профиле, чтобы
пользователь сверил его при первом подключении.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from db.models.users import User
from services.ssh_keys import fingerprint_of_public_key

_HOST_KEYS_DIR_ENV_VAR = "SFTP_HOST_KEYS_DIR"
_DEFAULT_HOST_KEYS_DIR = "/data/sftp-host-keys"
HOST_KEY_FILENAME = "ssh_host_ed25519_key"
_PUBLIC_KEY_SUFFIX = ".pub"
_PORT_ENV_VAR = "SFTP_PORT"
DEFAULT_SFTP_PORT = 2222
_HOST_ENV_VAR = "DOMAIN"
_DEFAULT_HOST = "localhost"


@dataclass(frozen=True, slots=True)
class SftpConnection:
    host: str
    port: int
    username: str | None
    host_key_fingerprint: str | None


def host_key_path() -> Path:
    """Приватный ключ хоста шлюза; рядом — публичный с суффиксом `.pub`."""
    return Path(os.environ.get(_HOST_KEYS_DIR_ENV_VAR, _DEFAULT_HOST_KEYS_DIR)) / HOST_KEY_FILENAME


def sftp_port() -> int:
    return int(os.environ.get(_PORT_ENV_VAR, DEFAULT_SFTP_PORT))


def host_key_fingerprint() -> str | None:
    """`None` — шлюз ещё ни разу не запускался и ключа хоста нет."""
    public_key_path = host_key_path().with_name(HOST_KEY_FILENAME + _PUBLIC_KEY_SUFFIX)
    try:
        return fingerprint_of_public_key(public_key_path.read_text())
    except OSError:
        return None


def sftp_connection_for(user: User) -> SftpConnection:
    return SftpConnection(
        host=os.environ.get(_HOST_ENV_VAR, _DEFAULT_HOST),
        port=sftp_port(),
        username=user.os_username,
        host_key_fingerprint=host_key_fingerprint(),
    )
