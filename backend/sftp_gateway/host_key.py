"""
Ключ хоста шлюза (раздел 20.4 ТЗ): создаётся при первом старте и хранится в
volume `sftp_host_keys`, чтобы отпечаток сервера не менялся при перезапуске
и переносе — иначе клиенты увидят предупреждение о подмене сервера.
"""

from __future__ import annotations

import os
from pathlib import Path

import asyncssh

HOST_KEY_ALGORITHM = "ssh-ed25519"
_PRIVATE_KEY_MODE = 0o600
_PUBLIC_KEY_SUFFIX = ".pub"


def load_or_create_host_key(path: Path) -> asyncssh.SSHKey:
    if path.exists():
        return asyncssh.read_private_key(path)
    key = asyncssh.generate_private_key(HOST_KEY_ALGORITHM)
    path.parent.mkdir(parents=True, exist_ok=True)
    key.write_private_key(path)
    os.chmod(path, _PRIVATE_KEY_MODE)
    key.write_public_key(path.with_name(path.name + _PUBLIC_KEY_SUFFIX))
    return key
