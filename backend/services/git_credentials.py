"""
Выбор Git-доступа без передачи секретов в URL и ответы API.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import asyncssh
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app_logging.config import get_logger
from db.models.repositories import GitCredential
from db.queries.git_credentials import replace_ssh_known_hosts
from db.session import async_session_factory
from services.crypto import decrypt
from services.errors import NotFoundError, ValidationError
from services.repository_validation import validate_git_url
from services.ssh_known_hosts import known_hosts_fingerprints, validate_known_hosts

MAX_TCP_PORT = 65535
HTTPS_TOKEN_KIND = "https_token"
SSH_KEY_KIND = "ssh_key"
_INVALID_CREDENTIAL_CHARACTERS = ("\n", "\r", "\x00")

logger = get_logger("git_credentials")


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
    if (credential.kind == HTTPS_TOKEN_KIND) != https:
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
    if kind == SSH_KEY_KIND:
        try:
            asyncssh.import_private_key(secret)
        except (ValueError, asyncssh.KeyImportError) as exc:
            raise ValidationError("Нужен приватный SSH-ключ без пароля") from exc
    elif any(c in secret for c in _INVALID_CREDENTIAL_CHARACTERS):
        raise ValidationError("HTTPS-токен не должен содержать переводы строк")


def validate_username(username: str) -> None:
    if any(character in username for character in _INVALID_CREDENTIAL_CHARACTERS):
        raise ValidationError("Недопустимый логин")


@dataclass(frozen=True, slots=True)
class GitlabApiAccess:
    """Адрес и токен GitLab API учётных данных Git (раздел 3.1, 16.2)."""

    base_url: str
    token: str


def gitlab_api_access(credential: GitCredential | None) -> GitlabApiAccess | None:
    """
    `None` — у репозитория нет учётных данных или опрос API выключен. Без
    своего токена API у HTTPS-доступа используется сам токен Git.
    """
    if credential is None or not credential.gitlab_api_enabled:
        return None
    if credential.gitlab_api_token_encrypted:
        token = decrypt(credential.gitlab_api_token_encrypted)
    elif credential.kind == HTTPS_TOKEN_KIND:
        token = decrypt(credential.secret_encrypted)
    else:
        return None
    return GitlabApiAccess(
        base_url=credential.gitlab_api_url or f"https://{credential.host}",
        token=token,
    )


def validate_gitlab_api(*, kind: str, enabled: bool, has_token: bool) -> None:
    """У SSH-ключа нет токена для API: при включённом опросе нужен свой."""
    if enabled and kind == SSH_KEY_KIND and not has_token:
        raise ValidationError("Для SSH-ключа укажите токен GitLab API")


def next_ssh_known_hosts(
    *,
    kind: str,
    stored: str | None,
    submitted: str | None,
    server_changed: bool,
) -> str | None:
    """
    Раздел 19.3: ключ хоста после сохранения учётных данных. Он есть только у
    SSH; ключ прежнего сервера к новому не относится. `submitted`: `None` —
    оставить, пустая строка — сбросить (запомнится при следующем
    подключении), текст — заменить проверенным.
    """
    if kind != SSH_KEY_KIND:
        return None
    if submitted is None:
        return None if server_changed else stored
    return validate_known_hosts(submitted) if submitted.strip() else None


async def remember_ssh_known_hosts(
    *,
    credential_id: uuid.UUID,
    previous: str | None,
    known_hosts: str,
) -> None:
    """
    Ключи Git-сервера после успешной операции по SSH: первый ключ (TOFU) или
    новые ключи, о которых сервер сообщил по доверенному соединению
    (`UpdateHostKeys`). Своя транзакция — операцию вызывающего кода она не
    затрагивает; сбой записи операцию git не роняет, ключ сохранится в
    следующий раз.
    """
    try:
        async with async_session_factory() as db_session:
            replaced = await replace_ssh_known_hosts(
                db_session,
                credential_id=credential_id,
                previous=previous,
                known_hosts=known_hosts,
            )
            await db_session.commit()
    except SQLAlchemyError:
        logger.exception("ssh_known_hosts_save_failed", credential_id=str(credential_id))
        return
    if replaced:
        logger.info(
            "ssh_known_hosts_saved",
            credential_id=str(credential_id),
            fingerprints=known_hosts_fingerprints(known_hosts),
        )
