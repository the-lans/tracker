"""
Очередь задач пользователя и слоты параллельного запуска (раздел 14.4 ТЗ).

Очередь — задачи автора в `ready`/`night_worker` по ручному приоритету, затем
по времени постановки. Слот занимает задача в работе или в `failed`, если её
запустил воркер очереди или у неё стоит галочка `occupies_slot`, и задача в
`refining` с идущим чатом при той же галочке. Ручная смена статуса — только в
статусы до запуска (раздел 14.1).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.tasks import Task
from services.errors import ConflictError, ValidationError
from services.refining_chat import CHAT_BUSY_MESSAGE
from services.session_heartbeat import is_session_alive
from services.task_status import (
    PRE_LAUNCH_STATUSES,
    QUEUE_STATUSES,
    RESETTABLE_STATUSES,
    reset_task_run,
    transition_task_status,
)
from services.tracker_day import TRACKER_TIMEZONE

if TYPE_CHECKING:
    from collections.abc import Iterable

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_queue")

# Воскресенье: от него отсчитывается день недели crontab.
_CRON_REFERENCE_SUNDAY = date(2000, 1, 2)
_DAYS_IN_WEEK = 7

# Статусы, в которых задача занимает слот, если её запустил воркер очереди
# или у неё стоит галочка `occupies_slot`. `failed` слот не освобождает:
# задача не пройдена (раздел 14.4).
SLOT_STATUSES = frozenset(
    {
        TaskStatus.QUEUED,
        TaskStatus.IN_PROGRESS,
        TaskStatus.PAUSED,
        TaskStatus.PLAN_REVIEW,
        TaskStatus.AWAITING_INPUT,
        TaskStatus.REBASE_CONFLICT,
        TaskStatus.FAILED,
    },
)

QUEUE_ORDER = (Task.queue_priority.desc(), Task.ready_at.asc(), Task.id.asc())


def slot_clause() -> sa.ColumnElement[bool]:
    """
    Задача в работе занимает слот автора (без чата в `refining`). Ожидание
    лимита держит слот по тем же правилам, кроме ушедшего ждать чата.
    """
    in_work = sa.or_(
        Task.status.in_(SLOT_STATUSES),
        sa.and_(
            Task.status == TaskStatus.AWAITING_LIMIT,
            Task.limit_wait_from_status.is_distinct_from(TaskStatus.REFINING),
        ),
    )
    return sa.and_(
        in_work,
        sa.or_(Task.launched_manually == sa.false(), Task.occupies_slot == sa.true()),
    )


async def _refining_chats_with_slot(
    db_session: AsyncSession,
    redis_client: Redis,
    user_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """
    Чаты в `refining` с галочкой `occupies_slot`, у которых жива сессия.
    """
    rows = await db_session.execute(
        sa.select(Task.id, Task.created_by).where(
            Task.created_by.in_(list(user_ids)),
            Task.status == TaskStatus.REFINING,
            Task.occupies_slot == sa.true(),
        ),
    )
    counts: dict[uuid.UUID, int] = {}
    for task_id, user_id in rows.all():
        if await is_session_alive(redis_client, task_id):
            counts[user_id] = counts.get(user_id, 0) + 1
    return counts


async def occupied_slots(
    db_session: AsyncSession,
    redis_client: Redis,
    user_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """
    Занятые слоты по пользователям; пользователи без занятых — не в словаре.
    """
    ids = list(user_ids)
    rows = await db_session.execute(
        sa.select(Task.created_by, sa.func.count())
        .where(Task.created_by.in_(ids), slot_clause())
        .group_by(Task.created_by),
    )
    counts: dict[uuid.UUID, int] = {user_id: count for user_id, count in rows.all()}
    for user_id, count in (await _refining_chats_with_slot(db_session, redis_client, ids)).items():
        counts[user_id] = counts.get(user_id, 0) + count
    return counts


async def queue_positions(
    db_session: AsyncSession,
    task_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """
    Место (с 1) задач в очереди их авторов; задачи вне очереди — не в словаре.
    """
    ids = list(task_ids)
    if not ids:
        return {}
    authors = sa.select(Task.created_by).where(Task.id.in_(ids)).scalar_subquery()
    ranked = (
        sa.select(
            Task.id.label("task_id"),
            sa.func.row_number()
            .over(partition_by=Task.created_by, order_by=QUEUE_ORDER)
            .label("position"),
        )
        .where(Task.status.in_(QUEUE_STATUSES), Task.created_by.in_(authors))
        .subquery()
    )
    rows = await db_session.execute(
        sa.select(ranked.c.task_id, ranked.c.position).where(ranked.c.task_id.in_(ids)),
    )
    return {task_id: int(position) for task_id, position in rows.all()}


@dataclass(frozen=True)
class QueueSummary:
    max_parallel_tasks: int
    occupied: int
    ready: int
    night_worker: int


async def queue_summary(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    user_id: uuid.UUID,
    max_parallel_tasks: int,
) -> QueueSummary:
    rows = await db_session.execute(
        sa.select(Task.status, sa.func.count())
        .where(Task.created_by == user_id, Task.status.in_(QUEUE_STATUSES))
        .group_by(Task.status),
    )
    by_status: dict[TaskStatus, int] = {status: count for status, count in rows.all()}
    occupied = await occupied_slots(db_session, redis_client, [user_id])
    return QueueSummary(
        max_parallel_tasks=max_parallel_tasks,
        occupied=occupied.get(user_id, 0),
        ready=by_status.get(TaskStatus.READY, 0),
        night_worker=by_status.get(TaskStatus.NIGHT_WORKER, 0),
    )


def night_window_active(now: datetime, *, start: time, end: time) -> bool:
    """
    Раздел 14.4: `now` внутри ночного окна по Москве — начало включительно,
    конец нет; окно может переходить через полночь.
    """
    moment = now.astimezone(TRACKER_TIMEZONE).time().replace(tzinfo=None)
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def moscow_cron(at: time, *, weekday: int | None = None) -> str:
    """
    Crontab по UTC (расписание Beat — `timezone="UTC"`) для времени по Москве;
    `weekday` — день недели crontab (0 — воскресенье), `None` — каждый день.
    Сдвиг через полночь переносит и день недели.
    """
    # Московское время без перехода на летнее: сдвиг одинаков в любой день.
    day = _CRON_REFERENCE_SUNDAY + timedelta(days=weekday or 0)
    utc = datetime.combine(day, at, tzinfo=TRACKER_TIMEZONE).astimezone(UTC)
    day_of_week = "*" if weekday is None else str(utc.isoweekday() % _DAYS_IN_WEEK)
    return f"{utc.minute} {utc.hour} * * {day_of_week}"


def night_window_cron(start: time) -> str:
    """Crontab по UTC для начала ночного окна."""
    return moscow_cron(start)


def validate_night_window(*, start: time, end: time) -> None:
    if start == end:
        raise ValidationError("Начало и конец ночного окна не должны совпадать")


async def change_task_status_manually(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    task: Task,
    to_status: TaskStatus,
) -> Task:
    """
    Раздел 14.1: пользователь переводит задачу между статусами до запуска, а
    завершённую или упавшую — в статус до запуска со сбросом прогона. Статусы
    выполнения меняет только система (409).
    """
    if to_status not in PRE_LAUNCH_STATUSES:
        raise ValidationError("Вручную задачу можно перевести только в статус до запуска")
    if task.status is to_status:
        return task
    if task.status in RESETTABLE_STATUSES:
        return await reset_task_run(db_session, task_id=task.id, to_status=to_status)
    if task.status not in PRE_LAUNCH_STATUSES:
        raise ConflictError("Статус задачи в работе меняет только система")
    if task.status is TaskStatus.REFINING and (
        task.chat_active or await is_session_alive(redis_client, task.id)
    ):
        raise ConflictError(CHAT_BUSY_MESSAGE)
    updated = await transition_task_status(
        db_session,
        task_id=task.id,
        from_status=task.status,
        to_status=to_status,
    )
    logger.info("task_status_changed_manually", task_id=str(task.id), to_status=to_status)
    return updated


def cancel_target_status(queued_from_status: TaskStatus | None) -> TaskStatus:
    """
    Раздел 14.2 «Отменить постановку»: задача возвращается в статус, из которого
    ушла в `queued`. Пришедшая из очереди из неё выходит (`defined`) — иначе
    воркер очереди тут же поставил бы её снова.
    """
    if queued_from_status is None:
        return TaskStatus.NEW
    if queued_from_status in QUEUE_STATUSES:
        return TaskStatus.DEFINED
    return queued_from_status
