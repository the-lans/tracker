"""Неизменяемое хранилище содержимого версий базы знаний."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path, PurePosixPath

from services.errors import PayloadTooLargeError, ValidationError

KNOWLEDGE_ROOT_ENV = "TRACKER_KNOWLEDGE_ROOT"
DEFAULT_KNOWLEDGE_ROOT = "/data/knowledge"
MAX_KNOWLEDGE_FILE_BYTES = 10 * 1024 * 1024
MAX_KNOWLEDGE_PATH_LENGTH = 1024
MAX_KNOWLEDGE_COMPONENT_BYTES = 255


def knowledge_root() -> Path:
    return Path(os.environ.get(KNOWLEDGE_ROOT_ENV, DEFAULT_KNOWLEDGE_ROOT))


def validate_knowledge_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > MAX_KNOWLEDGE_PATH_LENGTH
        or any(len(part.encode()) > MAX_KNOWLEDGE_COMPONENT_BYTES for part in value.split("/"))
        or path.is_absolute()
        or "\\" in value
        or any(ord(char) < 32 for char in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValidationError("Недопустимый путь в базе знаний")
    return value


def _object_path(key: str) -> Path:
    try:
        identifier = uuid.UUID(key)
    except ValueError as exc:
        raise ValidationError("Недопустимый идентификатор версии") from exc
    return knowledge_root() / "objects" / identifier.hex


def _write_object(content: bytes) -> str:
    key = str(uuid.uuid4())
    path = _object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return key


async def store_knowledge_content(content: bytes) -> str:
    if len(content) > MAX_KNOWLEDGE_FILE_BYTES:
        raise PayloadTooLargeError("Файл базы знаний превышает допустимый размер")
    return await asyncio.to_thread(_write_object, content)


async def read_knowledge_content(key: str) -> bytes:
    return await asyncio.to_thread(_object_path(key).read_bytes)
