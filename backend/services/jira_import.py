"""
Импорт задачи из Jira (раздел 15.6 ТЗ, решение №20 плана).

Подключение к Jira — личное, в профиле пользователя: адрес, email (Jira
Cloud) и токен, хранящийся зашифрованным. По ключу задачи заполняется форма
новой задачи — только то, для чего у задачи есть поля: ключ → код, summary →
название, description → описание, ссылка → `tasks.jira_issue_url`; вложения
при создании задачи копируются в её артефакты (раздел 14.3).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from clients.jira import AttachmentTooLargeError, JiraClient, JiraCredentials
from db.models.enums import AppLogLevel
from services.crypto import decrypt, encrypt
from services.errors import AppError, ValidationError
from services.task_artifacts import max_upload_bytes, save_artifact
from services.task_codes import validate_task_code

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task
    from db.models.users import User

logger = get_logger("jira_import")

_LOG_SOURCE = "jira_import"
_ISSUE_KEY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*-\d+")
_JIRA_URL_PATTERN = re.compile(r"https?://\S+")
_BROWSE_PATH = "/browse/"


@dataclass(frozen=True, slots=True)
class JiraAttachmentInfo:
    filename: str
    size: int


@dataclass(frozen=True, slots=True)
class JiraIssueDraft:
    """Поля формы новой задачи, заполненные из задачи Jira."""

    code: str
    title: str
    description: str
    issue_url: str
    attachments: list[JiraAttachmentInfo]


@dataclass(slots=True)
class AttachmentCopyResult:
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


async def update_jira_connection(
    db_session: AsyncSession,
    *,
    user: User,
    url: str,
    email: str | None,
    token: str | None,
) -> User:
    """``token``: `None` — оставить сохранённый, пустая строка — удалить."""
    if not _JIRA_URL_PATTERN.fullmatch(url):
        raise ValidationError("Адрес Jira — http(s)://…, например https://company.atlassian.net")
    user.jira_url = url.rstrip("/")
    user.jira_email = email or None
    if token is not None:
        user.jira_token_encrypted = encrypt(token) if token else None
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def clear_jira_connection(db_session: AsyncSession, *, user: User) -> User:
    user.jira_url = None
    user.jira_email = None
    user.jira_token_encrypted = None
    await db_session.commit()
    await db_session.refresh(user)
    return user


def jira_credentials_for(user: User) -> JiraCredentials:
    if not user.jira_url or not user.jira_token_encrypted:
        raise ValidationError("Подключите Jira в профиле: адрес и личный токен")
    return JiraCredentials(
        url=user.jira_url,
        email=user.jira_email,
        token=decrypt(user.jira_token_encrypted),
    )


def validate_issue_key(key: str) -> str:
    if not _ISSUE_KEY_PATTERN.fullmatch(key):
        raise ValidationError(f"Ключ задачи Jira — вида PROJ-123, получено {key!r}")
    return key.upper()


def jira_issue_url(user: User, key: str) -> str:
    """Ссылка на задачу Jira по ключу — без обращения к Jira."""
    credentials = jira_credentials_for(user)
    return f"{credentials.url}{_BROWSE_PATH}{validate_issue_key(key)}"


async def fetch_jira_draft(
    *,
    user: User,
    key: str,
    http_client: httpx.AsyncClient,
) -> JiraIssueDraft:
    client = JiraClient(credentials=jira_credentials_for(user), http_client=http_client)
    issue = await client.get_issue(validate_issue_key(key))
    return JiraIssueDraft(
        code=validate_task_code(issue.key),
        title=issue.summary,
        description=issue.description,
        issue_url=issue.browse_url,
        attachments=[
            JiraAttachmentInfo(filename=attachment.filename, size=attachment.size)
            for attachment in issue.attachments
        ],
    )


async def _single_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


async def _log_skipped(task: Task, filename: str, reason: str) -> None:
    logger.warning(
        "jira_attachment_skipped",
        task_id=str(task.id),
        filename=filename,
        reason=reason,
    )
    await write_app_log(
        level=AppLogLevel.WARNING,
        source=_LOG_SOURCE,
        message=f"Вложение Jira {filename!r} не скопировано в артефакты: {reason}",
        context={"task_id": str(task.id), "filename": filename},
        task_id=task.id,
    )


async def copy_jira_attachments(
    *,
    task: Task,
    user: User,
    key: str,
    http_client: httpx.AsyncClient,
) -> AttachmentCopyResult:
    """
    Вложения задачи Jira → артефакты задачи (раздел 15.6). Слишком большое
    или не скачавшееся вложение пропускается с записью в `app_logs`: создание
    задачи от этого не откатывается.
    """
    result = AttachmentCopyResult()
    client = JiraClient(credentials=jira_credentials_for(user), http_client=http_client)
    try:
        issue = await client.get_issue(validate_issue_key(key))
    except AppError as exc:
        await _log_skipped(task, "*", exc.message)
        return result
    limit = max_upload_bytes()
    for attachment in issue.attachments:
        filename = PurePosixPath(attachment.filename).name
        try:
            content = await client.download_attachment(attachment, max_bytes=limit)
            await save_artifact(task.code, filename, _single_chunk(content), max_bytes=limit)
        except AttachmentTooLargeError:
            await _log_skipped(task, filename, "больше допустимого размера артефакта")
            result.skipped.append(filename)
        except AppError as exc:
            await _log_skipped(task, filename, exc.message)
            result.skipped.append(filename)
        else:
            result.copied.append(filename)
    logger.info(
        "jira_attachments_copied",
        task_id=str(task.id),
        copied=len(result.copied),
        skipped=len(result.skipped),
    )
    return result
