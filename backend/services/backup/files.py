"""Общие операции с файлами копии: SHA-256 и размер каталога."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def tree_size(root: Path) -> int:
    """Сумма размеров обычных файлов каталога; недоступное не считается."""
    total = 0
    for directory, _, files in os.walk(root):
        for name in files:
            try:
                stat = os.lstat(os.path.join(directory, name))
            except OSError:
                continue
            total += stat.st_size
    return total
