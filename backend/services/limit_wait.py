"""
Ожидание сброса лимита LLM-аккаунтов — статус `awaiting_limit` (раздел 19.7 ТЗ).

Ворота лимита (`check_limit_gate`) проверяются перед ходом, пока воркер
держит пульс сессии: если все аккаунты автора на пороге или исчерпаны,
поднимается `LlmLimitWaitError`, и воркер переводит задачу в
`awaiting_limit` (`enter_limit_wait`), запомнив статус, из которого она
пришла, и ноду, с которой продолжить. После сброса воркер возвращает задачу
в прежний статус (`leave_limit_wait`). У ждущей задачи воркера нет, поэтому
«Остановить» и «Приостановить» выполняет API (`stop_limit_wait`,
`pause_limit_wait`).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import sqlalchemy as sa
from redis.exceptions import RedisError

from app_logging.config import get_logger
from db.models.enums import ManualRequestStatus, ManualRequestType, NodeType, TaskStatus
from db.models.pipelines import Node, TaskNode
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services.account_router import TaskAccountRouter
from services.errors import ConflictError
from services.library_commands import load_snapshot
from services.llm_account_choice import LlmLimitWaitError
from services.notifications import NotificationEvent, notify_task_event
from services.task_status import (
    LIMIT_WAIT_RETURN_STATUSES,
    first_unfinished_order_index,
    transition_task_status,
)
from services.tracker_day import TRACKER_TIMEZONE

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient

logger = get_logger("limit_wait")

# Ходы модели; скрипт и очистка контекста ворот лимита не ждут.
LLM_TURN_NODE_TYPES = frozenset(
    {NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.PLAN_PROMPT},
)


class LimitGate(Protocol):
    """Ворота лимита: до какого времени ход ждать сброса; None — ход можно начинать."""

    def __call__(self, *, node_type: NodeType | None = None) -> Awaitable[datetime | None]: ...


# «Приостановить» в ожидании: после сброса задача встанет на паузу.
_PAUSABLE_FROM_STATUSES = (TaskStatus.IN_PROGRESS, TaskStatus.REBASE_CONFLICT)
_NOTIFY_KEY = "push:limit_wait:{task_id}"
_MIN_NOTIFY_TTL_SECONDS = 60
_CLEARED_WAIT: dict[str, object] = {
    "limit_wait_from_status": None,
    "limit_wait_until": None,
    "limit_wait_order_index": None,
    "limit_wait_attempt": None,
}


@dataclass(frozen=True, slots=True)
class LimitResume:
    """Куда вернулась задача после ожидания и с какой ноды продолжить."""

    status: TaskStatus
    order_index: int | None
    attempt: int = 1


async def check_limit_gate(gate: LimitGate | None, *, node_type: NodeType) -> None:
    """
    Ворота перед ходом: `LlmLimitWaitError`, если ход надо отложить до сброса.
    Тип хода решает, какие аккаунты годятся (`plan_prompt` — не у всех
    провайдеров); ход без модели ворота не проверяет.
    """
    if gate is None or node_type not in LLM_TURN_NODE_TYPES:
        return
    until = await gate(node_type=node_type)
    if until is not None:
        raise LlmLimitWaitError(until)


async def manual_request_node_type(
    db_session: AsyncSession,
    request: TaskManualRequestQueue,
) -> NodeType:
    """Тип хода ручного запроса: свободный промт и пересказ — текстовый промт."""
    if request.request_type is not ManualRequestType.LIBRARY_PROMPT:
        return NodeType.PLAIN_PROMPT
    if request.command_snapshot_encrypted is not None:
        return load_snapshot(request).node_type
    node_type = await db_session.scalar(sa.select(Node.node_type).where(Node.id == request.node_id))
    return node_type or NodeType.PLAIN_PROMPT


async def _waiting_node_type(db_session: AsyncSession, task: Task) -> NodeType:
    """
    Ход, который ждёт сброса: конфликт ребейза разбирается первым, затем —
    первый запрос ручной очереди, затем — нода продолжения.
    """
    if task.limit_wait_from_status is TaskStatus.REBASE_CONFLICT:
        return NodeType.PLAIN_PROMPT
    request = await db_session.scalar(
        sa.select(TaskManualRequestQueue)
        .where(
            TaskManualRequestQueue.task_id == task.id,
            TaskManualRequestQueue.status == ManualRequestStatus.QUEUED,
        )
        .order_by(TaskManualRequestQueue.requested_at)
        .limit(1),
    )
    if request is not None:
        return await manual_request_node_type(db_session, request)
    if task.limit_wait_order_index is None:
        return NodeType.PLAIN_PROMPT
    node_type = await db_session.scalar(
        sa.select(Node.node_type)
        .join(TaskNode, TaskNode.node_id == Node.id)
        .where(
            TaskNode.task_id == task.id,
            TaskNode.order_index == task.limit_wait_order_index,
        ),
    )
    return node_type or NodeType.PLAIN_PROMPT


async def enter_limit_wait(
    db_session: AsyncSession,
    *,
    task: Task,
    until: datetime,
    redis_client: Redis,
    paused: bool = False,
    attempt: int = 1,
) -> bool:
    """
    Compare-and-swap текущего статуса в `awaiting_limit` (воркер, пока
    держит пульс). ``paused`` — пока ход ждал, пользователь нажал
    «Приостановить»: после сброса задача встанет на паузу. ``attempt`` —
    попытка ждущей ноды пайплайна. False — статус уже другой, ожидание не
    начато.
    """
    await db_session.refresh(task)
    from_status = task.status
    if from_status not in LIMIT_WAIT_RETURN_STATUSES:
        logger.info("limit_wait_skipped_status", task_id=str(task.id), status=from_status)
        return False
    order_index = (
        None
        if from_status is TaskStatus.REFINING
        else await first_unfinished_order_index(db_session, task.id)
    )
    resume_status = (
        TaskStatus.PAUSED if paused and from_status in _PAUSABLE_FROM_STATUSES else from_status
    )
    try:
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=from_status,
            to_status=TaskStatus.AWAITING_LIMIT,
            extra_values={
                "limit_wait_from_status": resume_status,
                "limit_wait_until": until,
                "limit_wait_order_index": order_index,
                "limit_wait_attempt": attempt,
            },
        )
    except ConflictError:
        logger.info("limit_wait_status_changed", task_id=str(task.id), status=from_status)
        return False
    await db_session.refresh(task)
    logger.info(
        "task_awaiting_limit",
        task_id=str(task.id),
        from_status=resume_status,
        until=until.isoformat(),
        order_index=order_index,
    )
    await _notify_once(db_session, redis_client=redis_client, task=task, until=until)
    return True


async def _notify_once(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    task: Task,
    until: datetime,
) -> None:
    """Раздел 18.2: одно уведомление на ожидание — ключ `SET NX` с TTL до сброса."""
    ttl = max(int((until - datetime.now(UTC)).total_seconds()), _MIN_NOTIFY_TTL_SECONDS)
    try:
        first = await redis_client.set(
            _NOTIFY_KEY.format(task_id=task.id),
            "1",
            nx=True,
            ex=ttl,
        )
    except RedisError:
        logger.warning("push_window_unavailable", push_event="llm_limit_wait")
        first = True
    if not first:
        return
    local = until.astimezone(TRACKER_TIMEZONE)
    await notify_task_event(
        db_session,
        event=NotificationEvent.LLM_LIMIT_WAIT,
        task=task,
        detail=(
            f"{task.code}: все LLM-аккаунты на пороге — задача ждёт сброса лимита "
            f"до {local:%H:%M} МСК"
        ),
    )


async def leave_limit_wait(db_session: AsyncSession, *, task: Task) -> LimitResume | None:
    """
    Compare-and-swap `awaiting_limit` → прежний статус (воркер, под пульсом).
    None — задачу уже остановили или продолжил другой воркер.
    """
    await db_session.refresh(task)
    from_status = task.limit_wait_from_status
    if task.status is not TaskStatus.AWAITING_LIMIT or from_status is None:
        return None
    order_index = task.limit_wait_order_index
    attempt = task.limit_wait_attempt or 1
    try:
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.AWAITING_LIMIT,
            to_status=from_status,
            extra_values=_CLEARED_WAIT,
        )
    except ConflictError:
        return None
    await db_session.refresh(task)
    logger.info("task_limit_wait_finished", task_id=str(task.id), status=from_status)
    return LimitResume(status=from_status, order_index=order_index, attempt=attempt)


async def stop_limit_wait(db_session: AsyncSession, *, task: Task) -> Task:
    """
    «Остановить» в ожидании (раздел 14.2): `failed` с точкой перезапуска на
    ноде, которая ждала; ожидание чата возвращает задачу в `refining`.
    """
    from_status = task.limit_wait_from_status
    if from_status is TaskStatus.REFINING:
        stopped = await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.AWAITING_LIMIT,
            to_status=TaskStatus.REFINING,
            extra_values=_CLEARED_WAIT,
        )
    else:
        order_index = task.limit_wait_order_index
        if order_index is None:
            order_index = await first_unfinished_order_index(db_session, task.id)
        stopped = await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.AWAITING_LIMIT,
            to_status=TaskStatus.FAILED,
            failed_order_index=order_index,
            extra_values=_CLEARED_WAIT,
        )
    logger.info("task_limit_wait_stopped", task_id=str(task.id), from_status=from_status)
    return stopped


async def pause_limit_wait(db_session: AsyncSession, *, task_id: uuid.UUID) -> bool:
    """
    «Приостановить» в ожидании: после сброса задача встанет на паузу. False —
    задача уже не ждёт или ждёт из чата либо паузы.
    """
    paused = await db_session.scalar(
        sa.update(Task)
        .where(
            Task.id == task_id,
            Task.status == TaskStatus.AWAITING_LIMIT,
            Task.limit_wait_from_status.in_(_PAUSABLE_FROM_STATUSES),
        )
        .values(limit_wait_from_status=TaskStatus.PAUSED)
        .returning(Task.id),
    )
    await db_session.commit()
    if paused is not None:
        logger.info("task_limit_wait_paused", task_id=str(task_id))
    return paused is not None


async def limit_waiting_tasks(db_session: AsyncSession) -> list[Task]:
    """Все ждущие лимита задачи — ближайший сброс первым."""
    stmt = (
        sa.select(Task)
        .where(Task.status == TaskStatus.AWAITING_LIMIT)
        .order_by(Task.limit_wait_until.asc().nulls_first(), Task.id)
    )
    return list((await db_session.execute(stmt)).scalars())


async def author_waits_for_limit(db_session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    """Раздел 14.4: ближайший сброс, которого ждут задачи автора; None — ожидания нет."""
    return await db_session.scalar(
        sa.select(sa.func.min(Task.limit_wait_until)).where(
            Task.created_by == user_id,
            Task.status == TaskStatus.AWAITING_LIMIT,
        ),
    )


async def limit_waits_to_resume(
    db_session: AsyncSession,
    *,
    redis_client: Redis,
    cliproxy: CliproxyManagementClient,
    now: datetime,
) -> list[uuid.UUID]:
    """
    Раздел 16.2 `check_llm_account_limits`: ждущие задачи, которые пора
    продолжить, — наступил сброс или у автора появился запущенный или
    свободный аккаунт (вход, включение, повышение порога).
    """
    resumable: list[uuid.UUID] = []
    # Ворота по автору и типу хода: `plan_prompt` годится не каждому аккаунту.
    author_gates: dict[tuple[uuid.UUID, NodeType], datetime | None] = {}
    for task in await limit_waiting_tasks(db_session):
        until = task.limit_wait_until
        if until is None or until <= now:
            resumable.append(task.id)
            continue
        node_type = await _waiting_node_type(db_session, task)
        key = (task.created_by, node_type)
        if key not in author_gates:
            router = TaskAccountRouter(
                db_session=db_session,
                redis_client=redis_client,
                task=task,
                cliproxy=cliproxy,
                clock=lambda: now,
            )
            author_gates[key] = await router.limit_gate(node_type=node_type)
        if author_gates[key] is None:
            resumable.append(task.id)
    return resumable
