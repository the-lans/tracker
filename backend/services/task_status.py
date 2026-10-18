"""Единая точка изменения `tasks.status` (раздел 14, 17.4, 17.5 ТЗ).

Раздел 14.3/план реализации ("Архитектурные решения" не по этому пункту,
но явно в тексте Этапа 9): все статусные переходы задачи консолидируются
здесь, а не разбросаны по сервисам Этапов 5-8. Compare-and-swap (раздел
17.4): переход проверяет, что ТЕКУЩИЙ статус совпадает с ожидаемым "откуда",
прежде чем менять — SQL `UPDATE ... WHERE status = :from_status` в одной
транзакции защищает от гонки, если два процесса одновременно решают
сменить статус одной и той же задачи.

Допустимые переходы (раздел 14.1) — граф диаграммы читается по описаниям
статусов (14.2), а не как строгая линейная цепочка: `plan_review` и
`awaiting_input` оба ответвляются от `in_progress` и оба возвращаются в
него; `rebase_conflict` и `failed` — самостоятельные ветки, а не
последовательные шаги друг после друга.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import NodeLogStatus, TaskStatus
from db.models.logs import NodeLog
from db.models.pipelines import TaskNode
from db.models.tasks import Task
from services.errors import ConflictError, ValidationError
from services.notifications import NotificationEvent, notify_task_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_status")

# Раздел 18.2: 4 из 7 обязательных к уведомлению событий — прямые переходы
# статуса задачи, а `transition_task_status` — единственная точка изменения
# `tasks.status` (раздел 14.3/план реализации, этап 9) — поэтому уведомление
# для них естественно живёт здесь, а не размазано по местам вызова.
_NOTIFICATION_EVENTS_BY_STATUS: dict[TaskStatus, NotificationEvent] = {
    TaskStatus.AWAITING_INPUT: NotificationEvent.AWAITING_DECISION,
    TaskStatus.PLAN_REVIEW: NotificationEvent.AWAITING_DECISION,
    TaskStatus.FAILED: NotificationEvent.FAILED,
    TaskStatus.DONE: NotificationEvent.DONE,
}

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.NEW: frozenset({TaskStatus.QUEUED}),
    TaskStatus.QUEUED: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.DONE,
            TaskStatus.PLAN_REVIEW,
            TaskStatus.AWAITING_INPUT,
            TaskStatus.REBASE_CONFLICT,
            TaskStatus.FAILED,
        },
    ),
    TaskStatus.PLAN_REVIEW: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.AWAITING_INPUT: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.REBASE_CONFLICT: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.FAILED: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.DONE: frozenset(),
}


async def _ensure_done_invariant(db_session: AsyncSession, task_id: uuid.UUID) -> None:
    """Раздел 17.5: переход в `done` невозможен, пока хотя бы одна включённая
    нода пайплайна не имеет записи `node_logs` со статусом `success`."""
    enabled_node_ids_stmt = sa.select(TaskNode.node_id).where(
        TaskNode.task_id == task_id,
        TaskNode.is_enabled == True,  # noqa: E712 — sa.Boolean-колонка, не Python bool
    )
    enabled_node_ids = set((await db_session.execute(enabled_node_ids_stmt)).scalars().all())
    if not enabled_node_ids:
        return

    succeeded_node_ids_stmt = sa.select(NodeLog.node_id).where(
        NodeLog.task_id == task_id,
        NodeLog.status == NodeLogStatus.SUCCESS,
        NodeLog.node_id.in_(enabled_node_ids),
    )
    succeeded_node_ids = set((await db_session.execute(succeeded_node_ids_stmt)).scalars().all())

    missing = enabled_node_ids - succeeded_node_ids
    if missing:
        raise ValidationError(
            f"Переход в done невозможен: {len(missing)} включённых нод(ы) ещё не имеют "
            "успешного выполнения",
        )


async def transition_task_status(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    from_status: TaskStatus,
    to_status: TaskStatus,
    failed_order_index: int | None = None,
) -> Task:
    """Compare-and-swap переход `tasks.status` (раздел 17.4).

    ``failed_order_index`` обязателен при переходе в `failed` (раздел
    17.5: "обязан сохранять точный order_index сбоя в
    tasks.last_failed_order_index") и игнорируется для любого другого
    перехода.
    """
    allowed = ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValidationError(f"Переход {from_status} -> {to_status} запрещён (раздел 14.1)")

    if to_status is TaskStatus.DONE:
        await _ensure_done_invariant(db_session, task_id)

    values: dict[str, object] = {"status": to_status}
    if to_status is TaskStatus.FAILED:
        if failed_order_index is None:
            raise ValidationError("Переход в failed требует failed_order_index (раздел 17.5)")
        values["last_failed_order_index"] = failed_order_index

    stmt = (
        sa.update(Task)
        .where(Task.id == task_id, Task.status == from_status)
        .values(**values)
        .returning(Task)
    )
    result = await db_session.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise ConflictError(
            f"Задача {task_id} уже не в статусе {from_status} — переход отменён "
            "(compare-and-swap, раздел 17.4)",
        )
    await db_session.commit()
    logger.info(
        "task_status_transitioned",
        task_id=str(task_id),
        from_status=from_status,
        to_status=to_status,
    )
    event = _NOTIFICATION_EVENTS_BY_STATUS.get(to_status)
    if event is not None:
        await notify_task_event(db_session, event=event, task=task)
    return task
