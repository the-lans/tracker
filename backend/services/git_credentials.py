"""
Выбор Git-доступа без передачи секретов в URL и ответы API.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

import asyncssh
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.repositories import GitCredential
from services.errors import NotFoundError, ValidationError
from services.repository_validation import validate_git_url

MAX_TCP_PORT = 65535
_INVALID_CREDENTIAL_CHARACTERS = ("\n", "\r", "\x00")


def git_host(url: str) -> tuple[str, bool]:
    validate_git_url(url)
    if "://" in url:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ValidationError("Некорректный Git URL") from exc
        if not parsed.hostname or (port is not None and not 1 <= port <= MAX_TCP_PORT):
            raise ValidationError("Некорректный Git-хост или порт")
        if parsed.scheme not in ("https", "ssh"):
            raise ValidationError("Используйте HTTPS или SSH для доступа к Git")
        if parsed.password is not None or (parsed.scheme != "ssh" and parsed.username is not None):
            raise ValidationError("Не указывайте логин или секрет в Git URL")
        if parsed.query or parsed.fragment:
            raise ValidationError("Git URL не должен содержать query или fragment")
        return (parsed.hostname or "").lower(), parsed.scheme == "https"
    return url.split("@", 1)[1].split(":", 1)[0].lower(), False


def validate_host(host: str) -> str:
    host = host.lower().strip()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
        raise ValidationError("Укажите имя Git-хоста без протокола, порта и пути")
    return host


async def resolve_credential(
    session: AsyncSession,
    credential_id: uuid.UUID | None,
    url: str,
) -> GitCredential | None:
    host, https = git_host(url)
    if credential_id is None:
        if not https:
            raise ValidationError("Для SSH-репозитория выберите учётные данные Git")
        return None
    credential = await lock_credential(session, credential_id)
    if credential.host != host:
        raise ValidationError("Хост репозитория не соответствует учётным данным Git")
    if (credential.kind == "https_token") != https:
        raise ValidationError("Протокол Git URL не соответствует типу учётных данных")
    return credential


async def lock_credential(session: AsyncSession, credential_id: uuid.UUID) -> GitCredential:
    row = await session.scalar(
        sa.select(GitCredential)
        .where(GitCredential.id == credential_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFoundError("Учётные данные Git не найдены")
    return row


def validate_secret(kind: str, secret: str) -> None:
    if kind == "ssh_key":
        try:
            asyncssh.import_private_key(secret)
        except (ValueError, asyncssh.KeyImportError) as exc:
            raise ValidationError("Нужен приватный SSH-ключ без пароля") from exc
    elif any(c in secret for c in _INVALID_CREDENTIAL_CHARACTERS):
        raise ValidationError("HTTPS-токен не должен содержать переводы строк")


def validate_username(username: str) -> None:
    if any(character in username for character in _INVALID_CREDENTIAL_CHARACTERS):
        raise ValidationError("Недопустимый логин")
