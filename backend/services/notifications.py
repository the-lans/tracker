"""События, требующие обязательного уведомления (раздел 18.2 ТЗ), и лента событий (18.4).

Единая точка построения `PushMessage` и записи события ленты — вызывается
из мест, где эти события фактически происходят (см. ссылки в докстринге
каждого события ниже), не дублируя логику по местам вызова. Получатель
события задачи — её автор (`tasks.created_by`); напоминание о давно не
использованном SSH-ключе (раздел 16.2) получает владелец ключа; события
бэкапа и периодических задач — все активные администраторы одной записью
ленты. Успехи попадают только в ленту — push уходит о сбоях и о том, что
ждёт пользователя.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa
from redis.exceptions import RedisError

from app_logging.config import bind_task_context, get_logger
from db.models.enums import EventCategory, UserRole
from db.models.users import User
from services.events import EventDraft, record_event
from services.push_notifications import PushMessage, send_push_to_user
from services.redis_connection import redis_connection

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task


logger = get_logger("notifications")


class NotificationEvent(StrEnum):
    """
    Раздел 18.2 — события, требующие обязательного уведомления: семь
    исходных, постоянный сбой GitLab API (раздел 17.3) и напоминания
    периодических задач (раздел 16.2).
    """

    AWAITING_DECISION = "awaiting_decision"  # awaiting_input ИЛИ plan_review
    FAILED = "failed"
    REMOTE_CONTROL_DISCONNECTED = "remote_control_disconnected"
    AUTOSTART_FAILED = "autostart_failed"
    # Раздел 14.4: задача очереди не прошла проверки запуска.
    QUEUE_LAUNCH_FAILED = "queue_launch_failed"
    DONE = "done"
    LIBRARY_PROMPT_FAILED = "library_prompt_failed"
    MANUAL_QUEUE_REQUEST_EXPIRED = "manual_queue_request_expired"
    # Раздел 17.3: постоянный сбой GitLab API — уведомление без повторов.
    GITLAB_SYNC_FAILED = "gitlab_sync_failed"
    # Раздел 16.2: `cleanup_stale_worktrees` и `detect_awaiting_input_timeout`.
    CLEANUP_REMINDER = "cleanup_reminder"
    AWAITING_DECISION_REMINDER = "awaiting_decision_reminder"
    # Раздел 16.2: `revoke_stale_sshfs_keys` — событие пользователя, не задачи.
    STALE_SSH_KEY = "stale_ssh_key"
    # Раздел 19.7: аккаунту нужен повторный вход — владельцу аккаунта.
    LLM_LOGIN_REQUIRED = "llm_login_required"
    # Раздел 19.7: все аккаунты автора на пороге — задача ждёт сброса лимита.
    LLM_LIMIT_WAIT = "llm_limit_wait"
    # Раздел 20.4: сбой бэкапа в S3 или проверки восстановления — администраторам.
    BACKUP_FAILED = "backup_failed"
    BACKUP_VERIFY_FAILED = "backup_verify_failed"
    # Раздел 18.4: только в ленте администраторов, без push.
    BACKUP_SUCCEEDED = "backup_succeeded"
    BACKUP_VERIFIED = "backup_verified"
    # Раздел 16.3, 18.4: периодическая задача сломалась / снова работает —
    # только при смене итога, а не на каждый запуск.
    PERIODIC_TASK_FAILED = "periodic_task_failed"
    PERIODIC_TASK_RECOVERED = "periodic_task_recovered"


_TITLES: dict[NotificationEvent, str] = {
    NotificationEvent.AWAITING_DECISION: "Задача ожидает решения",
    NotificationEvent.FAILED: "Задача завершилась с ошибкой",
    NotificationEvent.REMOTE_CONTROL_DISCONNECTED: "Мост remote-control недоступен",
    NotificationEvent.AUTOSTART_FAILED: "Не удалось запустить задачу по расписанию",
    NotificationEvent.QUEUE_LAUNCH_FAILED: "Не удалось запустить задачу из очереди",
    NotificationEvent.DONE: "Задача выполнена",
    NotificationEvent.LIBRARY_PROMPT_FAILED: "Промт библиотеки завершился с ошибкой",
    NotificationEvent.MANUAL_QUEUE_REQUEST_EXPIRED: "Запрос из очереди отменён по таймауту",
    NotificationEvent.GITLAB_SYNC_FAILED: "Не удалось получить статус MR из GitLab",
    NotificationEvent.CLEANUP_REMINDER: "Пора очистить директорию репозиториев",
    NotificationEvent.AWAITING_DECISION_REMINDER: "Задача всё ещё ждёт решения",
    NotificationEvent.STALE_SSH_KEY: "SSH-ключ давно не использовался",
    NotificationEvent.LLM_LOGIN_REQUIRED: "LLM-аккаунту нужен повторный вход",
    NotificationEvent.LLM_LIMIT_WAIT: "Задача ждёт сброса лимита LLM-аккаунтов",
    NotificationEvent.BACKUP_FAILED: "Резервное копирование в S3 не удалось",
    NotificationEvent.BACKUP_VERIFY_FAILED: "Проверка резервной копии не прошла",
    NotificationEvent.BACKUP_SUCCEEDED: "Резервная копия загружена в S3",
    NotificationEvent.BACKUP_VERIFIED: "Резервная копия проверена",
    NotificationEvent.PERIODIC_TASK_FAILED: "Периодическая задача завершилась с ошибкой",
    NotificationEvent.PERIODIC_TASK_RECOVERED: "Периодическая задача снова выполняется успешно",
}

EVENT_CATEGORIES: dict[NotificationEvent, EventCategory] = {
    NotificationEvent.AWAITING_DECISION: EventCategory.TASK,
    NotificationEvent.FAILED: EventCategory.TASK,
    NotificationEvent.REMOTE_CONTROL_DISCONNECTED: EventCategory.TASK,
    NotificationEvent.AUTOSTART_FAILED: EventCategory.TASK,
    NotificationEvent.QUEUE_LAUNCH_FAILED: EventCategory.TASK,
    NotificationEvent.DONE: EventCategory.TASK,
    NotificationEvent.LIBRARY_PROMPT_FAILED: EventCategory.TASK,
    NotificationEvent.MANUAL_QUEUE_REQUEST_EXPIRED: EventCategory.TASK,
    NotificationEvent.GITLAB_SYNC_FAILED: EventCategory.TASK,
    NotificationEvent.CLEANUP_REMINDER: EventCategory.TASK,
    NotificationEvent.AWAITING_DECISION_REMINDER: EventCategory.TASK,
    NotificationEvent.STALE_SSH_KEY: EventCategory.PROFILE,
    NotificationEvent.LLM_LOGIN_REQUIRED: EventCategory.LLM_ACCOUNT,
    NotificationEvent.LLM_LIMIT_WAIT: EventCategory.LLM_ACCOUNT,
    NotificationEvent.BACKUP_FAILED: EventCategory.BACKUP,
    NotificationEvent.BACKUP_VERIFY_FAILED: EventCategory.BACKUP,
    NotificationEvent.BACKUP_SUCCEEDED: EventCategory.BACKUP,
    NotificationEvent.BACKUP_VERIFIED: EventCategory.BACKUP,
    NotificationEvent.PERIODIC_TASK_FAILED: EventCategory.PERIODIC,
    NotificationEvent.PERIODIC_TASK_RECOVERED: EventCategory.PERIODIC,
}

# Раздел 18.4: успехи — только в ленте событий.
FEED_ONLY_EVENTS = frozenset(
    {
        NotificationEvent.BACKUP_SUCCEEDED,
        NotificationEvent.BACKUP_VERIFIED,
        NotificationEvent.PERIODIC_TASK_RECOVERED,
    },
)


# Раздел 18.2: в режиме «подтверждать каждое действие» агент запрашивает
# разрешения сериями по несколько за секунды — серия даёт одно уведомление
# на задачу за окно, о дальнейших запросах пользователь узнаёт в виджете.
AWAITING_DECISION_PUSH_WINDOW_SECONDS = 30
_PUSH_WINDOWS_SECONDS: dict[NotificationEvent, int] = {
    NotificationEvent.AWAITING_DECISION: AWAITING_DECISION_PUSH_WINDOW_SECONDS,
}


def task_push_window_key(task_id: uuid.UUID, event: NotificationEvent) -> str:
    return f"push:window:{event}:{task_id}"


async def _push_suppressed(task: Task, event: NotificationEvent) -> bool:
    """
    `SET NX` с TTL (раздел 17.4): уведомление уже ушло в текущем окне. Без
    Redis уведомление отправляется — лишнее лучше пропущенного.
    """
    window = _PUSH_WINDOWS_SECONDS.get(event)
    if window is None:
        return False
    try:
        async with redis_connection() as redis_client:
            opened = await redis_client.set(
                task_push_window_key(task.id, event),
                "1",
                nx=True,
                ex=window,
            )
    except RedisError:
        logger.warning("push_window_unavailable", push_event=event.value, exc_info=True)
        return False
    return not opened


async def notify_task_event(
    db_session: AsyncSession,
    *,
    event: NotificationEvent,
    task: Task,
    detail: str = "",
) -> None:
    """Событие ленты и push-уведомление автору задачи (`task.created_by`)."""
    with bind_task_context(task.id):
        if await _push_suppressed(task, event):
            logger.info("push_suppressed_in_window", push_event=event.value)
            return
    body = detail or f"{task.code}: {task.title}"
    await record_event(db_session, _draft(event, body, task_id=task.id), user_id=task.created_by)
    message = PushMessage(
        title=_TITLES[event],
        body=body,
        data={"task_id": str(task.id), "event": event.value},
    )
    # Периодические проверки обходят задачи вне воркера сессии — итог отправки
    # всё равно ищется по `task_id` задачи (раздел 17.2).
    with bind_task_context(task.id):
        await send_push_to_user(db_session, user_id=task.created_by, message=message)


async def notify_user_event(
    db_session: AsyncSession,
    *,
    event: NotificationEvent,
    user_id: uuid.UUID,
    detail: str,
) -> None:
    """Событие ленты и push-уведомление пользователю — не о задаче."""
    await record_event(db_session, _draft(event, detail), user_id=user_id)
    message = PushMessage(title=_TITLES[event], body=detail, data={"event": event.value})
    await send_push_to_user(db_session, user_id=user_id, message=message)


async def notify_admins(
    db_session: AsyncSession,
    *,
    event: NotificationEvent,
    detail: str,
) -> None:
    """
    Одна запись в ленте администраторов и push каждому активному
    администратору — кроме событий только для ленты (`FEED_ONLY_EVENTS`).
    """
    await record_event(db_session, _draft(event, detail), user_id=None)
    if event in FEED_ONLY_EVENTS:
        return
    admin_ids = (
        await db_session.scalars(
            sa.select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True)),
        )
    ).all()
    message = PushMessage(title=_TITLES[event], body=detail, data={"event": event.value})
    for admin_id in admin_ids:
        await send_push_to_user(db_session, user_id=admin_id, message=message)


def _draft(event: NotificationEvent, body: str, *, task_id: uuid.UUID | None = None) -> EventDraft:
    return EventDraft(
        category=EVENT_CATEGORIES[event],
        event_type=event.value,
        title=_TITLES[event],
        body=body,
        task_id=task_id,
    )
