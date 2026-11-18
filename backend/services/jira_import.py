"""
Импорт задачи из Jira (раздел 15.6 ТЗ, решение №20 плана).

Адрес Jira — системная настройка (`system_settings.jira_url`, задаёт
администратор): сервер, к которому обращается backend, пользователь не
выбирает. Доступ — личный, в профиле: email (Jira Cloud) и токен, хранящийся
зашифрованным. По ключу задачи заполняется форма новой задачи — только то,
для чего у задачи есть поля: ключ → код, summary → название, description →
описание, ссылка → `tasks.jira_issue_url`; вложения после создания задачи
копируются в её артефакты фоновой задачей (раздел 14.3,
`tasks/jira_attachments.py`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import httpx
import sqlalchemy as sa

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from clients.jira import AttachmentTooLargeError, JiraClient, JiraCredentials
from db.models.enums import AppLogLevel
from db.models.tasks import Task
from services.crypto import decrypt, encrypt
from services.errors import AppError, ConflictError, ValidationError
from services.system_settings import get_jira_url
from services.task_artifacts import max_upload_bytes, save_artifact
from services.task_codes import validate_task_code

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

logger = get_logger("jira_import")

_LOG_SOURCE = "jira_import"
_ISSUE_KEY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*-\d+")
_BROWSE_PATH = "/browse/"
_BROWSE_KEY_PATTERN = re.compile(r"/browse/([A-Za-z][A-Za-z0-9_]*-\d+)")
# Запрос к Jira — по действию пользователя: ждать дольше нет смысла.
JIRA_TIMEOUT_SECONDS = 30.0
# Больше этого HTML описания не сохраняется: показывается обычный текст.
DESCRIPTION_HTML_MAX_CHARS = 500_000
_COPY_PENDING_KEY = "jira_attachments_pending:{task_id}"
# Страховка на случай потерянной фоновой задачи: флаг «копируются» не держит
# опрос списка артефактов вечно.
COPY_PENDING_TTL_SECONDS = 60 * 60


def new_jira_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=JIRA_TIMEOUT_SECONDS)


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
    email: str | None,
    token: str | None,
) -> User:
    """``token``: `None` — оставить сохранённый, пустая строка — удалить."""
    user.jira_email = email or None
    if token is not None:
        user.jira_token_encrypted = encrypt(token) if token else None
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def clear_jira_connection(db_session: AsyncSession, *, user: User) -> User:
    user.jira_email = None
    user.jira_token_encrypted = None
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def jira_credentials_for(db_session: AsyncSession, user: User) -> JiraCredentials:
    url = await get_jira_url(db_session)
    if url is None:
        raise ValidationError(
            "Адрес Jira не задан — его указывает администратор в «Системных настройках»",
        )
    if not user.jira_token_encrypted:
        raise ValidationError("Добавьте личный токен Jira в профиле")
    return JiraCredentials(
        url=url,
        email=user.jira_email,
        token=decrypt(user.jira_token_encrypted),
    )


def validate_issue_key(key: str) -> str:
    if not _ISSUE_KEY_PATTERN.fullmatch(key):
        raise ValidationError(f"Ключ задачи Jira — вида PROJ-123, получено {key!r}")
    return key.upper()


async def jira_issue_url(db_session: AsyncSession, user: User, key: str) -> str:
    """Ссылка на задачу Jira по ключу — без обращения к Jira."""
    credentials = await jira_credentials_for(db_session, user)
    return f"{credentials.url}{_BROWSE_PATH}{validate_issue_key(key)}"


async def fetch_jira_draft(
    db_session: AsyncSession,
    *,
    user: User,
    key: str,
    http_client: httpx.AsyncClient,
) -> JiraIssueDraft:
    credentials = await jira_credentials_for(db_session, user)
    client = JiraClient(credentials=credentials, http_client=http_client)
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


def _copy_pending_key(task_id: uuid.UUID) -> str:
    return _COPY_PENDING_KEY.format(task_id=task_id)


async def mark_attachment_copy_pending(redis_client: Redis, task_id: uuid.UUID) -> None:
    """
    Ставится до постановки фоновой задачи: страница новой задачи перечитывает
    артефакты, пока вложения копируются (раздел 15.6).
    """
    await redis_client.set(_copy_pending_key(task_id), "1", ex=COPY_PENDING_TTL_SECONDS)


async def clear_attachment_copy_pending(redis_client: Redis, task_id: uuid.UUID) -> None:
    await redis_client.delete(_copy_pending_key(task_id))


async def attachment_copy_pending(redis_client: Redis, task_id: uuid.UUID) -> bool:
    return bool(await redis_client.exists(_copy_pending_key(task_id)))


def unique_artifact_name(filename: str, taken: set[str]) -> str:
    """
    Одноимённые вложения Jira (например, вставленные скриншоты `image.png`)
    не перезаписывают друг друга: `image.png`, `image (2).png`, …
    """
    path = PurePosixPath(filename)
    candidate = filename
    number = 1
    while candidate in taken:
        number += 1
        candidate = f"{path.stem} ({number}){path.suffix}"
    taken.add(candidate)
    return candidate


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


async def save_description_html(
    db_session: AsyncSession,
    *,
    task: Task,
    description: str,
    description_html: str | None,
) -> bool:
    """
    HTML описания из Jira → `tasks.description_html` (раздел 15.6). Только если
    описание задачи осталось таким, как в Jira: условие в самом UPDATE — правка
    описания между чтением и записью не оставит HTML от прежнего текста.
    """
    if not description_html or len(description_html) > DESCRIPTION_HTML_MAX_CHARS:
        return False
    result = await db_session.execute(
        sa.update(Task)
        .where(Task.id == task.id, Task.description == description)
        .values(description_html=description_html)
        .returning(Task.id),
    )
    await db_session.commit()
    return result.scalar_one_or_none() is not None


def issue_key_of_url(url: str | None) -> str | None:
    """Ключ задачи из сохранённой ссылки `…/browse/PROJ-123`; нет ссылки или ключа — None."""
    match = _BROWSE_KEY_PATTERN.search(url or "")
    return match.group(1).upper() if match else None


async def refresh_description_html(
    db_session: AsyncSession,
    *,
    task: Task,
    user: User,
    http_client: httpx.AsyncClient,
) -> str:
    """
    Подгружает отрисованное описание у задачи, импортированной из Jira раньше
    (раздел 15.6); возвращает ключ задачи Jira — по нему копируются вложения.
    Только пока описание задачи совпадает с описанием в Jira: иначе HTML
    показывал бы другой текст.
    """
    key = issue_key_of_url(task.jira_issue_url)
    if key is None:
        raise ConflictError("У задачи нет ссылки на задачу Jira")
    credentials = await jira_credentials_for(db_session, user)
    issue = await JiraClient(credentials=credentials, http_client=http_client).get_issue(key)
    if issue.description != task.description:
        raise ConflictError("Описание задачи отличается от описания в Jira — обновить нельзя")
    if not issue.description_html:
        raise ConflictError("Jira не вернула отрисованное описание")
    saved = await save_description_html(
        db_session,
        task=task,
        description=issue.description,
        description_html=issue.description_html,
    )
    if not saved:
        raise ConflictError("Описание изменилось или слишком большое для показа")
    return key


async def copy_jira_attachments(
    db_session: AsyncSession,
    *,
    task: Task,
    user: User,
    key: str,
    http_client: httpx.AsyncClient,
) -> AttachmentCopyResult:
    """
    Вложения задачи Jira → артефакты задачи (раздел 15.6). Слишком большое
    или не скачавшееся вложение пропускается с записью в `app_logs`.
    Повторный запуск записывает те же файлы под теми же именами.
    """
    result = AttachmentCopyResult()
    try:
        credentials = await jira_credentials_for(db_session, user)
        client = JiraClient(credentials=credentials, http_client=http_client)
        issue = await client.get_issue(validate_issue_key(key))
    except AppError as exc:
        await _log_skipped(task, "*", exc.message)
        return result
    await save_description_html(
        db_session,
        task=task,
        description=issue.description,
        description_html=issue.description_html,
    )
    limit = max_upload_bytes()
    taken: set[str] = set()
    for attachment in issue.attachments:
        filename = unique_artifact_name(PurePosixPath(attachment.filename).name, taken)
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
