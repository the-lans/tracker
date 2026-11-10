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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from redis.exceptions import RedisError

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from services.account_router import TaskAccountRouter
from services.errors import ConflictError
from services.llm_account_choice import LlmLimitWaitError
from services.notifications import NotificationEvent, notify_task_event
from services.task_queue import NIGHT_WINDOW_TIMEZONE
from services.task_status import (
    LIMIT_WAIT_RETURN_STATUSES,
    first_unfinished_order_index,
    transition_task_status,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient

logger = get_logger("limit_wait")

# Ворота лимита: до какого времени ход ждать сброса; None — ход можно начинать.
type LimitGate = Callable[[], Awaitable[datetime | None]]

# «Приостановить» в ожидании: после сброса задача встанет на паузу.
_PAUSABLE_FROM_STATUSES = (TaskStatus.IN_PROGRESS, TaskStatus.REBASE_CONFLICT)
_NOTIFY_KEY = "push:limit_wait:{task_id}"
_MIN_NOTIFY_TTL_SECONDS = 60
_CLEARED_WAIT: dict[str, object] = {
    "limit_wait_from_status": None,
    "limit_wait_until": None,
    "limit_wait_order_index": None,
}


@dataclass(frozen=True, slots=True)
class LimitResume:
    """Куда вернулась задача после ожидания и с какой ноды продолжить."""

    status: TaskStatus
    order_index: int | None


async def check_limit_gate(gate: LimitGate | None) -> None:
    """Ворота перед ходом: `LlmLimitWaitError`, если ход надо отложить до сброса."""
    if gate is None:
        return
    until = await gate()
    if until is not None:
        raise LlmLimitWaitError(until)


async def enter_limit_wait(
    db_session: AsyncSession,
    *,
    task: Task,
    until: datetime,
    redis_client: Redis,
    paused: bool = False,
) -> bool:
    """
    Compare-and-swap текущего статуса в `awaiting_limit` (воркер, пока
    держит пульс). ``paused`` — пока ход ждал, пользователь нажал
    «Приостановить»: после сброса задача встанет на паузу. False — статус
    уже другой, ожидание не начато.
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
    local = until.astimezone(NIGHT_WINDOW_TIMEZONE)
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
    return LimitResume(status=from_status, order_index=order_index)


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
    author_gates: dict[uuid.UUID, datetime | None] = {}
    for task in await limit_waiting_tasks(db_session):
        until = task.limit_wait_until
        if until is None or until <= now:
            resumable.append(task.id)
            continue
        if task.created_by not in author_gates:
            router = TaskAccountRouter(
                db_session=db_session,
                redis_client=redis_client,
                task=task,
                cliproxy=cliproxy,
                clock=lambda: now,
            )
            author_gates[task.created_by] = await router.limit_gate()
        if author_gates[task.created_by] is None:
            resumable.append(task.id)
    return resumable
