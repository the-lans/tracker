"""События, требующие обязательного уведомления (раздел 18.2 ТЗ).

Единая точка построения `PushMessage` для всех 7 событий раздела 18.2 —
вызывается из мест, где эти события фактически происходят (см. ссылки в
докстринге каждого события ниже), не дублируя логику по местам вызова.
Получатель события задачи — её автор (`tasks.created_by`); раздел 18 не
называет других получателей (например, всех админов). Напоминание о давно
не использованном SSH-ключе (раздел 16.2) получает владелец ключа.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from redis.exceptions import RedisError

from app_logging.config import bind_task_context, get_logger
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


_TITLES: dict[NotificationEvent, str] = {
    NotificationEvent.AWAITING_DECISION: "Задача ожидает решения",
    NotificationEvent.FAILED: "Задача завершилась с ошибкой",
    NotificationEvent.REMOTE_CONTROL_DISCONNECTED: "Мост remote-control недоступен",
    NotificationEvent.AUTOSTART_FAILED: "Не удалось запустить задачу по расписанию",
    NotificationEvent.DONE: "Задача выполнена",
    NotificationEvent.LIBRARY_PROMPT_FAILED: "Промт библиотеки завершился с ошибкой",
    NotificationEvent.MANUAL_QUEUE_REQUEST_EXPIRED: "Запрос из очереди отменён по таймауту",
    NotificationEvent.GITLAB_SYNC_FAILED: "Не удалось получить статус MR из GitLab",
    NotificationEvent.CLEANUP_REMINDER: "Пора очистить директорию репозиториев",
    NotificationEvent.AWAITING_DECISION_REMINDER: "Задача всё ещё ждёт решения",
    NotificationEvent.STALE_SSH_KEY: "SSH-ключ давно не использовался",
}


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
    """Отправляет push-уведомление автору задачи (`task.created_by`)."""
    with bind_task_context(task.id):
        if await _push_suppressed(task, event):
            logger.info("push_suppressed_in_window", push_event=event.value)
            return
    message = PushMessage(
        title=_TITLES[event],
        body=detail or f"{task.code}: {task.title}",
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
    """Push-уведомление о событии пользователя, не связанном с задачей."""
    message = PushMessage(title=_TITLES[event], body=detail, data={"event": event.value})
    await send_push_to_user(db_session, user_id=user_id, message=message)
