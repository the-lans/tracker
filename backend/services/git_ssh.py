"""
SSH-доступ git воркера к Git-серверу (раздел 19.3): ключ хоста проверяется
всегда. Сохранённый ключ — строго; без него ключ запоминается при первом
подключении (как у ssh по умолчанию). По доверенному соединению ssh узнаёт и
новые ключи сервера (`UpdateHostKeys`), поэтому плановая смена ключей не
останавливает задачи.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from db.models.repositories import GitCredential
from services.git_credentials import remember_ssh_known_hosts

_KNOWN_HOSTS_FILE = "known_hosts"
_STRICT_HOST_KEY_CHECKING = "yes"
_FIRST_USE_HOST_KEY_CHECKING = "accept-new"
# Так ssh сообщает о ключе хоста, не совпавшем с сохранённым.
_HOST_KEY_REJECTED_MARKER = "Host key verification failed"
HOST_KEY_REJECTED_MESSAGE = (
    "Ключ Git-сервера не совпал с сохранённым: сервер подменён или сменил ключ. "
    "Сверьте отпечаток и сбросьте ключ хоста в «Учётных данных Git»"
)


def write_known_hosts(directory: Path, credential: GitCredential) -> Path:
    """Временный `known_hosts` операции с сохранёнными ключами сервера."""
    known_hosts_path = directory / _KNOWN_HOSTS_FILE
    known_hosts_path.write_text(credential.ssh_known_hosts or "")
    return known_hosts_path


def ssh_command(*, secret_path: Path, known_hosts_path: Path, strict: bool) -> str:
    """`GIT_SSH_COMMAND`: свой ключ, без вопросов, свой `known_hosts`."""
    checking = _STRICT_HOST_KEY_CHECKING if strict else _FIRST_USE_HOST_KEY_CHECKING
    return (
        f"ssh -i {shlex.quote(str(secret_path))} -o IdentitiesOnly=yes -o BatchMode=yes "
        f"-o StrictHostKeyChecking={checking} -o UpdateHostKeys=yes "
        f"-o UserKnownHostsFile={shlex.quote(str(known_hosts_path))}"
    )


async def remember_host_keys(credential: GitCredential, known_hosts_path: Path) -> None:
    """
    Первый ключ сервера или новые его ключи — после операции без исключения.
    """
    known_hosts = known_hosts_path.read_text()
    if known_hosts.strip() and known_hosts != (credential.ssh_known_hosts or ""):
        await remember_ssh_known_hosts(
            credential_id=credential.id,
            previous=credential.ssh_known_hosts,
            known_hosts=known_hosts,
        )


def host_key_rejected(stderr: str) -> bool:
    return _HOST_KEY_REJECTED_MARKER in stderr
