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

from services.push_notifications import PushMessage, send_push_to_user

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task


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


async def notify_task_event(
    db_session: AsyncSession,
    *,
    event: NotificationEvent,
    task: Task,
    detail: str = "",
) -> None:
    """Отправляет push-уведомление автору задачи (`task.created_by`)."""
    message = PushMessage(
        title=_TITLES[event],
        body=detail or f"{task.code}: {task.title}",
        data={"task_id": str(task.id), "event": event.value},
    )
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
