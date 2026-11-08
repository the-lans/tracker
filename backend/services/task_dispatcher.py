"""
Воркер очереди задач: дневной и ночной проход (раздел 14.4, 16.2 ТЗ).

Проход под распределённой блокировкой Redis (правило 12 CLAUDE.md): ставит в
очередь задачи с наступившим автозапуском, затем по кругу пользователей
переводит задачи очереди в `queued`, пока у автора есть свободный слот, а у
воркера сессий — свободный процесс. Таск сессии ставит вызывающий код после
фиксации перехода.
"""

from __future__ import annotations

import os
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import AppLogLevel, TaskStatus
from db.models.logs import AppLog
from db.models.tasks import Task
from db.models.users import User
from services.autostart import run_scheduled_autostart_check
from services.distributed_lock import LockNotAcquiredError, acquire_lock
from services.errors import ConflictError, ServiceUnavailableError, ValidationError
from services.maintenance import maintenance_active
from services.notifications import NotificationEvent, notify_task_event
from services.session_heartbeat import is_session_alive
from services.system_settings import get_system_settings
from services.task_launch import ensure_task_launchable
from services.task_queue import QUEUE_ORDER, night_window_active, occupied_slots
from services.task_status import QUEUE_STATUSES, SESSION_ACTIVE_STATUSES, transition_task_status

if TYPE_CHECKING:
    from datetime import datetime

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_dispatcher")

DISPATCH_LOCK_KEY = "task-dispatcher:lock"
# Проход занимает секунды; TTL страхует от процесса, умершего с блокировкой.
DISPATCH_LOCK_TTL_SECONDS = 120
# Раздел 14.4: об одной причине отказа задача напоминает не чаще раза в сутки.
LAUNCH_FAILURE_NOTICE_TTL_SECONDS = 24 * 60 * 60
# Число процессов воркера сессий (`--concurrency` сервиса session-worker).
SESSION_WORKER_CONCURRENCY_ENV = "SESSION_WORKER_CONCURRENCY"
DEFAULT_SESSION_WORKER_CONCURRENCY = 4
_DAY_STATUSES = frozenset({TaskStatus.READY})


@dataclass(slots=True)
class DispatchResult:
    launched_task_ids: list[uuid.UUID] = field(default_factory=list)
    failed_task_ids: list[uuid.UUID] = field(default_factory=list)
    # Другой проход уже идёт или идёт обновление сервера — ничего не сделано.
    skipped: bool = False


def session_worker_concurrency() -> int:
    value = os.environ.get(SESSION_WORKER_CONCURRENCY_ENV)
    return int(value) if value else DEFAULT_SESSION_WORKER_CONCURRENCY


async def _busy_session_processes(db_session: AsyncSession, redis_client: Redis) -> int:
    """Процессы воркера сессий, занятые задачами в работе и чатами в `refining`."""
    busy_statuses = (TaskStatus.QUEUED, *SESSION_ACTIVE_STATUSES)
    busy = await db_session.scalar(
        sa.select(sa.func.count()).where(Task.status.in_(busy_statuses)),
    )
    refining_ids = (
        await db_session.execute(sa.select(Task.id).where(Task.status == TaskStatus.REFINING))
    ).scalars()
    chats = [task_id for task_id in refining_ids if await is_session_alive(redis_client, task_id)]
    return int(busy or 0) + len(chats)


async def _queues_by_user(
    db_session: AsyncSession,
    statuses: frozenset[TaskStatus],
) -> dict[uuid.UUID, deque[Task]]:
    """Очереди активных пользователей в порядке очереди (раздел 14.4)."""
    stmt = (
        sa.select(Task)
        .join(User, User.id == Task.created_by)
        .where(Task.status.in_(statuses), User.is_active == sa.true())
        .order_by(Task.created_by, *QUEUE_ORDER)
    )
    queues: dict[uuid.UUID, deque[Task]] = {}
    for task in (await db_session.execute(stmt)).scalars().all():
        queues.setdefault(task.created_by, deque()).append(task)
    return queues


async def _free_slots(
    db_session: AsyncSession,
    redis_client: Redis,
    user_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    rows = await db_session.execute(
        sa.select(User.id, User.max_parallel_tasks).where(User.id.in_(user_ids)),
    )
    limits = {user_id: limit for user_id, limit in rows.all()}
    occupied = await occupied_slots(db_session, redis_client, user_ids)
    return {user_id: limits[user_id] - occupied.get(user_id, 0) for user_id in user_ids}


async def _report_launch_failure(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    task: Task,
    error: ValidationError,
) -> None:
    """Задача остаётся в очереди; уведомление — раз в сутки на задачу и причину."""
    logger.error("queue_task_launch_failed", task_id=str(task.id), error=str(error))
    db_session.add(
        AppLog(
            level=AppLogLevel.ERROR,
            source="task_dispatcher",
            message=f"Не удалось запустить задачу из очереди: {error}",
            context={"task_id": str(task.id)},
            task_id=task.id,
        ),
    )
    await db_session.commit()
    notice_key = f"task-dispatcher:failed:{task.id}:{error}"
    if await redis_client.set(notice_key, "1", nx=True, ex=LAUNCH_FAILURE_NOTICE_TTL_SECONDS):
        await notify_task_event(
            db_session,
            event=NotificationEvent.QUEUE_LAUNCH_FAILED,
            task=task,
            detail=f"{task.code}: не удалось запустить из очереди — {error}",
        )


async def _launch(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    task: Task,
    result: DispatchResult,
) -> bool:
    """`True` — задача переведена в `queued` и заняла слот."""
    try:
        await ensure_task_launchable(db_session, task)
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=task.status,
            to_status=TaskStatus.QUEUED,
            extra_values={"launched_manually": False, "queued_from_status": task.status},
        )
    except ConflictError:
        # Статус успели сменить (пользователь, «Выполнить») — задачи в очереди уже нет.
        logger.info("queue_task_left_queue", task_id=str(task.id))
        return False
    except ValidationError as exc:
        result.failed_task_ids.append(task.id)
        await _report_launch_failure(db_session, redis_client, task=task, error=exc)
        return False
    result.launched_task_ids.append(task.id)
    logger.info("queue_task_launched", task_id=str(task.id))
    return True


async def _dispatch_round_robin(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    queues: dict[uuid.UUID, deque[Task]],
    free_slots: dict[uuid.UUID, int],
    free_processes: int,
    result: DispatchResult,
) -> None:
    """По одной задаче каждого пользователя за круг, пока есть слоты и процессы."""
    active = deque(user_id for user_id in queues if free_slots[user_id] > 0)
    while active and free_processes > 0:
        user_id = active.popleft()
        queue = queues[user_id]
        while queue:
            if await _launch(db_session, redis_client, task=queue.popleft(), result=result):
                free_slots[user_id] -= 1
                free_processes -= 1
                break
        if queue and free_slots[user_id] > 0:
            active.append(user_id)


async def dispatch_queued_tasks(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    now: datetime,
    night: bool = False,
) -> DispatchResult:
    """
    Проход воркера очереди. ``night`` — ночной воркер: берёт `night_worker`
    независимо от времени; дневной берёт их только внутри ночного окна.
    """
    result = DispatchResult()
    try:
        async with acquire_lock(
            redis_client,
            DISPATCH_LOCK_KEY,
            ttl_seconds=DISPATCH_LOCK_TTL_SECONDS,
            busy_message="Проход воркера очереди уже выполняется",
        ):
            await _dispatch_locked(db_session, redis_client, now=now, night=night, result=result)
    except LockNotAcquiredError:
        logger.info("task_dispatch_already_running")
        result.skipped = True
    return result


async def _dispatch_locked(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    now: datetime,
    night: bool,
    result: DispatchResult,
) -> None:
    if await maintenance_active(redis_client):
        # Раздел 20.6: задачи остаются в очереди до первого прохода после обновления.
        logger.info("task_dispatch_deferred_by_maintenance")
        result.skipped = True
        return
    await run_scheduled_autostart_check(db_session, now=now)
    settings = await get_system_settings(db_session)
    in_window = night or night_window_active(
        now,
        start=settings.night_window_start,
        end=settings.night_window_end,
    )
    queues = await _queues_by_user(db_session, QUEUE_STATUSES if in_window else _DAY_STATUSES)
    if not queues:
        return
    free_processes = session_worker_concurrency() - await _busy_session_processes(
        db_session,
        redis_client,
    )
    try:
        await _dispatch_round_robin(
            db_session,
            redis_client,
            queues=queues,
            free_slots=await _free_slots(db_session, redis_client, list(queues)),
            free_processes=free_processes,
            result=result,
        )
    except ServiceUnavailableError:
        logger.info("task_dispatch_interrupted_by_maintenance")
    logger.info(
        "task_dispatch_finished",
        launched=len(result.launched_task_ids),
        failed=len(result.failed_task_ids),
        night_window=in_window,
    )
