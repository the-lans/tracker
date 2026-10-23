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
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import (
    AppLogLevel,
    LibraryPromptRunStatus,
    ManualRequestStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    TaskStatus,
)
from db.models.logs import AppLog, NodeLog
from db.models.pipelines import TaskNode
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
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
    # `queued -> new` — «Отменить постановку» (раздел 14.2).
    TaskStatus.QUEUED: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.NEW}),
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.DONE,
            TaskStatus.PAUSED,
            TaskStatus.PLAN_REVIEW,
            TaskStatus.AWAITING_INPUT,
            TaskStatus.REBASE_CONFLICT,
            TaskStatus.FAILED,
        },
    ),
    # «Приостановить» (раздел 14.2): продолжить, остановить или поймать
    # конфликт ребейза, пока задача стоит на паузе. Ручной промт на паузе
    # выполняется сразу и тоже может спросить пользователя.
    TaskStatus.PAUSED: frozenset(
        {
            TaskStatus.IN_PROGRESS,
            TaskStatus.FAILED,
            TaskStatus.REBASE_CONFLICT,
            TaskStatus.PLAN_REVIEW,
            TaskStatus.AWAITING_INPUT,
        },
    ),
    # После решения задача возвращается туда, откуда ушла в ожидание.
    TaskStatus.PLAN_REVIEW: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.PAUSED}),
    TaskStatus.AWAITING_INPUT: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.PAUSED}),
    TaskStatus.REBASE_CONFLICT: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.FAILED}),
    # `-> new` — «Вернуть в новые» (раздел 14.2): сменить пайплайн и запустить заново.
    TaskStatus.FAILED: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.NEW}),
    TaskStatus.DONE: frozenset({TaskStatus.NEW}),
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
    extra_values: dict[str, object] | None = None,
) -> Task:
    """Compare-and-swap переход `tasks.status` (раздел 17.4).

    ``failed_order_index`` обязателен при переходе в `failed` (раздел
    17.5: "обязан сохранять точный order_index сбоя в
    tasks.last_failed_order_index") и игнорируется для любого другого
    перехода. ``extra_values`` — поля, меняемые в том же UPDATE, что и
    статус (отмена постановки заодно выключает автозапуск).
    """
    allowed = ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise ValidationError(f"Переход {from_status} -> {to_status} запрещён (раздел 14.1)")

    if to_status is TaskStatus.DONE:
        await _ensure_done_invariant(db_session, task_id)

    values: dict[str, object] = {**(extra_values or {}), "status": to_status}
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


_UNFINISHED_NODE_LOG_STATUSES = (
    NodeLogStatus.PENDING,
    NodeLogStatus.RUNNING,
    NodeLogStatus.AWAITING_DECISION,
)
_AWAITING_STATUSES = (TaskStatus.AWAITING_INPUT, TaskStatus.PLAN_REVIEW)
# Раздел 8.2: сессией задачи владеет воркер ровно в этих статусах — ручные
# запросы принимаются в её очередь, только пока она активна.
SESSION_ACTIVE_STATUSES = frozenset(
    {
        TaskStatus.IN_PROGRESS,
        TaskStatus.PAUSED,
        TaskStatus.PLAN_REVIEW,
        TaskStatus.AWAITING_INPUT,
        TaskStatus.REBASE_CONFLICT,
    },
)
# Статусы, из которых `failed` достижим напрямую (раздел 14.1).
FAILABLE_STATUSES = (TaskStatus.IN_PROGRESS, TaskStatus.PAUSED, TaskStatus.REBASE_CONFLICT)


async def first_unfinished_order_index(db_session: AsyncSession, task_id: uuid.UUID) -> int:
    """`order_index` первой включённой ноды без успешного выполнения в пайплайне.

    Если все включённые ноды уже успешны (сбой случился после них — например,
    при пуше), возвращает индекс за последней нодой: перезапуск с этой точки
    не повторяет ни одной ноды и сразу переходит к завершению задачи.
    """
    succeeded_node_ids = (
        sa.select(NodeLog.node_id)
        .where(
            NodeLog.task_id == task_id,
            NodeLog.trigger_type == NodeLogTriggerType.PIPELINE,
            NodeLog.status == NodeLogStatus.SUCCESS,
            # NOT IN с NULL в подзапросе отбросил бы все строки.
            NodeLog.node_id.is_not(None),
        )
        .scalar_subquery()
    )
    unfinished_stmt = sa.select(sa.func.min(TaskNode.order_index)).where(
        TaskNode.task_id == task_id,
        TaskNode.is_enabled == True,  # noqa: E712 — sa.Boolean-колонка, не Python bool
        TaskNode.node_id.not_in(succeeded_node_ids),
    )
    unfinished = (await db_session.execute(unfinished_stmt)).scalar_one_or_none()
    if unfinished is not None:
        return int(unfinished)
    last_stmt = sa.select(sa.func.max(TaskNode.order_index)).where(TaskNode.task_id == task_id)
    last = (await db_session.execute(last_stmt)).scalar_one_or_none()
    return 0 if last is None else int(last) + 1


async def fail_task_from_current_status(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    failed_order_index: int,
) -> bool:
    """
    Переводит задачу в `failed` из того статуса, в котором она сейчас.

    Пока шёл ход, задачу могли поставить на паузу, поймать конфликт ребейза
    или перевести в ожидание решения (раздел 14.1). Из `plan_review` и
    `awaiting_input` прямого перехода в `failed` нет — сначала возврат в
    `in_progress`. `False` — статус уже терминальный или неожиданный.
    """
    task = await db_session.get(Task, task_id, populate_existing=True)
    if task is None:
        return False
    from_status = task.status
    if from_status in _AWAITING_STATUSES:
        await transition_task_status(
            db_session,
            task_id=task_id,
            from_status=from_status,
            to_status=TaskStatus.IN_PROGRESS,
        )
        from_status = TaskStatus.IN_PROGRESS
    elif from_status not in FAILABLE_STATUSES:
        logger.warning(
            "task_not_failed_unexpected_status",
            task_id=str(task_id),
            status=from_status,
        )
        return False
    await transition_task_status(
        db_session,
        task_id=task_id,
        from_status=from_status,
        to_status=TaskStatus.FAILED,
        failed_order_index=failed_order_index,
    )
    return True


async def fail_task_after_error(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    error: BaseException,
) -> None:
    """
    Раздел 17.3: падение Celery-задачи сессии не оставляет `running`.

    Незавершённые записи `node_logs` закрываются как `failed`, задача
    переводится в `failed` с точкой перезапуска (раздел 17.5), ошибка
    пишется в `app_logs`. Ручной запрос, на котором упала сессия, тоже
    закрывается: очередь берёт только `queued`, и `processing`-запрос
    (а с ним «выполняется» у промта библиотеки) иначе завис бы навсегда.
    """
    await db_session.rollback()
    now = datetime.now(UTC)
    await db_session.execute(
        sa.update(NodeLog)
        .where(NodeLog.task_id == task_id, NodeLog.status.in_(_UNFINISHED_NODE_LOG_STATUSES))
        .values(status=NodeLogStatus.FAILED, finished_at=now),
    )
    await db_session.execute(
        sa.update(TaskManualRequestQueue)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.status == ManualRequestStatus.PROCESSING,
        )
        .values(status=ManualRequestStatus.DONE, processed_at=now),
    )
    await db_session.execute(
        sa.update(TaskLibraryPrompt)
        .where(
            TaskLibraryPrompt.task_id == task_id,
            TaskLibraryPrompt.last_run_status == LibraryPromptRunStatus.RUNNING,
        )
        .values(last_run_status=LibraryPromptRunStatus.FAILED, last_run_at=now),
    )
    db_session.add(
        AppLog(
            level=AppLogLevel.ERROR,
            source="session_worker",
            message=f"Сессия задачи завершилась с ошибкой: {error}",
            context={"task_id": str(task_id), "error_type": type(error).__name__},
            task_id=task_id,
        ),
    )
    await db_session.commit()

    await fail_task_from_current_status(
        db_session,
        task_id=task_id,
        failed_order_index=await first_unfinished_order_index(db_session, task_id),
    )


# Раздел 14.2 «Вернуть в новые»: только у задачи без живой сессии.
RESETTABLE_STATUSES = frozenset({TaskStatus.FAILED, TaskStatus.DONE})


async def reset_task_to_new(db_session: AsyncSession, *, task_id: uuid.UUID) -> Task:
    """
    Возвращает завершённую или упавшую задачу в `new`: пайплайн и состав нод
    снова можно менять, «Запустить» пройдёт пайплайн с начала в той же
    сессии. Точка перезапуска и автозапуск сбрасываются.
    """
    task = await db_session.get(Task, task_id, populate_existing=True)
    if task is None or task.status not in RESETTABLE_STATUSES:
        raise ConflictError("Вернуть в новые можно только завершённую или упавшую задачу")
    return await transition_task_status(
        db_session,
        task_id=task_id,
        from_status=task.status,
        to_status=TaskStatus.NEW,
        extra_values={"last_failed_order_index": None, "auto_start_enabled": False},
    )
