"""
Воркер очереди: дневной и ночной проход (раздел 14.4, 16.2 ТЗ).
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from kombu.exceptions import OperationalError

import services.task_dispatcher as dispatcher_module
from db.models.enums import AppLogLevel, TaskStatus
from db.models.logs import AppLog
from db.models.tasks import Task
from db.models.users import User
from services.errors import ValidationError
from services.maintenance import MAINTENANCE_KEY
from services.notifications import NotificationEvent
from services.system_settings import get_system_settings
from services.task_dispatcher import (
    DISPATCH_LOCK_KEY,
    SESSION_WORKER_CONCURRENCY_ENV,
    dispatch_queued_tasks,
)
from services.task_launch import ensure_task_launchable
from tasks import periodic
from tasks.session_worker import run_task_session
from tests.factories import make_pipeline, make_task, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

# Дневное время по Москве — вне ночного окна по умолчанию (03:15–07:00).
_DAY = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
# 04:00 МСК — внутри ночного окна.
_NIGHT = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _many_session_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SESSION_WORKER_CONCURRENCY_ENV, "10")


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> list[NotificationEvent]:
    events: list[NotificationEvent] = []

    async def capture(_db: AsyncSession, *, event: NotificationEvent, **_: object) -> None:
        events.append(event)

    monkeypatch.setattr(dispatcher_module, "notify_task_event", capture)
    return events


async def _user(db_session: AsyncSession, *, limit: int = 3) -> User:
    user = await make_user(db_session)
    user.max_parallel_tasks = limit
    await db_session.flush()
    return user


async def _queued(
    db_session: AsyncSession,
    user: User,
    *,
    status: TaskStatus = TaskStatus.READY,
    priority: int = 100,
    minutes_ago: int = 10,
) -> Task:
    """
    Задача очереди, готовая к запуску: пайплайн есть, LLM-нод нет.
    """
    pipeline = await make_pipeline(db_session, created_by=user.id)
    return await make_task(
        db_session,
        created_by=user.id,
        pipeline_id=pipeline.id,
        status=status,
        queue_priority=priority,
        ready_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


async def _dispatch(
    db_session: AsyncSession,
    redis_client: Redis,
    *,
    now: datetime = _DAY,
) -> dispatcher_module.DispatchResult:
    return await dispatch_queued_tasks(db_session, redis_client, now=now)


async def _status(db_session: AsyncSession, task: Task) -> TaskStatus:
    await db_session.refresh(task)
    return task.status


class TestLimit:
    async def test_order_and_limit(self, db_session: AsyncSession, redis_client: Redis) -> None:
        user = await _user(db_session, limit=2)
        first = await _queued(db_session, user, minutes_ago=30)
        later = await _queued(db_session, user, minutes_ago=5)
        urgent = await _queued(db_session, user, priority=200, minutes_ago=1)

        result = await _dispatch(db_session, redis_client)

        assert result.launched_task_ids == [urgent.id, first.id]
        assert await _status(db_session, later) is TaskStatus.READY
        await db_session.refresh(first)
        assert (first.status, first.launched_manually, first.queued_from_status) == (
            TaskStatus.QUEUED,
            False,
            TaskStatus.READY,
        )

    @pytest.mark.parametrize(
        ("busy_status", "launched_manually", "occupies_slot", "launched"),
        [
            pytest.param(TaskStatus.IN_PROGRESS, False, False, 0, id="слот занят задачей очереди"),
            pytest.param(TaskStatus.FAILED, False, False, 0, id="failed держит слот"),
            pytest.param(TaskStatus.IN_PROGRESS, True, False, 1, id="ручной запуск без галочки"),
            pytest.param(TaskStatus.IN_PROGRESS, True, True, 0, id="ручной запуск с галочкой"),
            pytest.param(TaskStatus.DONE, False, False, 1, id="done освободил слот"),
        ],
    )
    async def test_occupied(
        self,
        *,
        db_session: AsyncSession,
        redis_client: Redis,
        busy_status: TaskStatus,
        launched_manually: bool,
        occupies_slot: bool,
        launched: int,
    ) -> None:
        user = await _user(db_session, limit=1)
        await make_task(
            db_session,
            created_by=user.id,
            status=busy_status,
            launched_manually=launched_manually,
            occupies_slot=occupies_slot,
        )
        await _queued(db_session, user)

        result = await _dispatch(db_session, redis_client)

        assert len(result.launched_task_ids) == launched

    async def test_users_independent(self, db_session: AsyncSession, redis_client: Redis) -> None:
        busy = await _user(db_session, limit=1)
        await make_task(db_session, created_by=busy.id, status=TaskStatus.IN_PROGRESS)
        await _queued(db_session, busy)
        free = await _user(db_session, limit=1)
        free_task = await _queued(db_session, free)

        result = await _dispatch(db_session, redis_client)

        assert result.launched_task_ids == [free_task.id]

    async def test_blocked_user_skipped(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        user = await _user(db_session)
        user.is_active = False
        await _queued(db_session, user)

        result = await _dispatch(db_session, redis_client)

        assert result.launched_task_ids == []


class TestSessionProcesses:
    async def test_round_robin(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(SESSION_WORKER_CONCURRENCY_ENV, "3")
        first_user, second_user = await _user(db_session), await _user(db_session)
        first = [await _queued(db_session, first_user, minutes_ago=m) for m in (30, 20, 10)]
        second = [await _queued(db_session, second_user, minutes_ago=m) for m in (30, 20)]

        result = await _dispatch(db_session, redis_client)

        launched = set(result.launched_task_ids)
        # Кто из пользователей первый в круге, не задано: у каждого запускаются его
        # самые ранние задачи, всего — по числу свободных процессов.
        counts = [sum(task.id in launched for task in queue) for queue in (first, second)]
        assert sorted(counts) == [1, 2]
        for queue, count in zip((first, second), counts, strict=True):
            assert {task.id for task in queue[:count]} <= launched

    async def test_busy_processes(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv(SESSION_WORKER_CONCURRENCY_ENV, "1")
        other = await _user(db_session)
        await make_task(
            db_session,
            created_by=other.id,
            status=TaskStatus.IN_PROGRESS,
            launched_manually=True,
        )
        await _queued(db_session, await _user(db_session))

        result = await _dispatch(db_session, redis_client)

        assert result.launched_task_ids == []


class TestNightWindow:
    @pytest.mark.parametrize(
        ("now", "launched"),
        [pytest.param(_DAY, False, id="днём"), pytest.param(_NIGHT, True, id="ночью")],
    )
    async def test_night_worker(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        now: datetime,
        launched: bool,
    ) -> None:
        task = await _queued(db_session, await _user(db_session), status=TaskStatus.NIGHT_WORKER)

        result = await _dispatch(db_session, redis_client, now=now)

        assert (task.id in result.launched_task_ids) is launched

    async def test_window_from_settings(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        settings = await get_system_settings(db_session)
        settings.night_window_start, settings.night_window_end = time(11, 0), time(13, 0)
        await db_session.flush()
        task = await _queued(db_session, await _user(db_session), status=TaskStatus.NIGHT_WORKER)

        # 09:00 UTC — 12:00 МСК.
        result = await _dispatch(db_session, redis_client, now=_DAY)

        assert result.launched_task_ids == [task.id]

    async def test_shared_order_with_ready(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        user = await _user(db_session, limit=1)
        await _queued(db_session, user, minutes_ago=5)
        night = await _queued(db_session, user, status=TaskStatus.NIGHT_WORKER, minutes_ago=50)

        result = await _dispatch(db_session, redis_client, now=_NIGHT)

        assert result.launched_task_ids == [night.id]


class TestLaunchFailure:
    async def _failing(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[Task, Task]:
        user = await _user(db_session, limit=1)
        broken = await _queued(db_session, user, minutes_ago=30)
        good = await _queued(db_session, user, minutes_ago=10)
        original = ensure_task_launchable

        async def launchable(db: AsyncSession, task: Task) -> None:
            if task.id == broken.id:
                raise ValidationError("Сначала выберите пайплайн задачи")
            await original(db, task)

        monkeypatch.setattr(dispatcher_module, "ensure_task_launchable", launchable)
        return broken, good

    async def test_next_task_launched(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
        notifications: list[NotificationEvent],
    ) -> None:
        broken, good = await self._failing(db_session, monkeypatch)

        result = await _dispatch(db_session, redis_client)

        assert (result.launched_task_ids, result.failed_task_ids) == ([good.id], [broken.id])
        assert await _status(db_session, broken) is TaskStatus.READY
        logs = (
            (await db_session.execute(sa.select(AppLog).where(AppLog.task_id == broken.id)))
            .scalars()
            .all()
        )
        assert [(log.level, log.source) for log in logs] == [
            (AppLogLevel.ERROR, "task_dispatcher"),
        ]
        assert notifications == [NotificationEvent.QUEUE_LAUNCH_FAILED]

    async def test_notified_once(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
        notifications: list[NotificationEvent],
    ) -> None:
        broken, _ = await self._failing(db_session, monkeypatch)

        await _dispatch(db_session, redis_client)
        await _dispatch(db_session, redis_client)

        logs = (
            (await db_session.execute(sa.select(AppLog).where(AppLog.task_id == broken.id)))
            .scalars()
            .all()
        )
        assert (len(logs), notifications) == (1, [NotificationEvent.QUEUE_LAUNCH_FAILED])


class TestSkipped:
    async def test_lock_taken(self, db_session: AsyncSession, redis_client: Redis) -> None:
        task = await _queued(db_session, await _user(db_session))
        await redis_client.set(DISPATCH_LOCK_KEY, "other")

        result = await _dispatch(db_session, redis_client)

        assert result.skipped
        assert await _status(db_session, task) is TaskStatus.READY

    async def test_maintenance(self, db_session: AsyncSession, redis_client: Redis) -> None:
        task = await _queued(db_session, await _user(db_session))
        await redis_client.set(MAINTENANCE_KEY, "1")

        result = await _dispatch(db_session, redis_client)

        assert result.skipped
        assert await _status(db_session, task) is TaskStatus.READY

    async def test_lock_released(self, db_session: AsyncSession, redis_client: Redis) -> None:
        await _dispatch(db_session, redis_client)

        assert not await redis_client.exists(DISPATCH_LOCK_KEY)

    async def test_repeat_is_idempotent(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task = await _queued(db_session, await _user(db_session))

        first = await _dispatch(db_session, redis_client)
        second = await _dispatch(db_session, redis_client)

        assert (first.launched_task_ids, second.launched_task_ids) == ([task.id], [])


class TestAutostart:
    async def test_queued_and_launched(self, db_session: AsyncSession, redis_client: Redis) -> None:
        user = await _user(db_session)
        pipeline = await make_pipeline(db_session, created_by=user.id)
        task = await make_task(
            db_session,
            created_by=user.id,
            pipeline_id=pipeline.id,
            status=TaskStatus.DEFINED,
            auto_start_enabled=True,
            scheduled_start_at=_DAY - timedelta(minutes=1),
        )

        result = await _dispatch(db_session, redis_client)

        assert result.launched_task_ids == [task.id]
        await db_session.refresh(task)
        assert (task.status, task.auto_start_enabled) == (TaskStatus.QUEUED, False)


class TestCeleryTasks:
    @pytest.mark.parametrize("task_name", ["dispatch_ready_tasks", "dispatch_night_tasks"])
    async def test_enqueue_sessions(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        task_name: str,
    ) -> None:
        task = await _queued(db_session, await _user(db_session))
        task.status = TaskStatus.QUEUED
        task.queued_from_status = TaskStatus.READY
        await db_session.commit()
        launched_id = task.id
        calls: list[datetime] = []
        bodies: list[object] = []
        enqueued: list[tuple[str, bool]] = []

        async def dispatch(*_args: object, now: datetime) -> object:
            calls.append(now)
            return dispatcher_module.DispatchResult(launched_task_ids=[launched_id])

        monkeypatch.setattr(periodic, "dispatch_queued_tasks", dispatch)
        monkeypatch.setattr(periodic, "_run_periodic", lambda _name, body: bodies.append(body))
        monkeypatch.setattr(
            run_task_session,
            "delay",
            lambda task_id, *, queued_only: enqueued.append((task_id, queued_only)),
        )

        getattr(periodic, task_name)()
        [body] = bodies
        await body(db_session)  # type: ignore[operator]

        assert (len(calls), enqueued) == (1, [(str(launched_id), True)])


class TestDeliveryRecovery:
    async def test_partial_dispatch_delivers_committed_tasks(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _user(db_session)
        good = await _queued(db_session, user, priority=200)
        broken = await _queued(db_session, user, priority=100)
        good_id, broken_id = good.id, broken.id
        await db_session.commit()
        original = ensure_task_launchable

        async def interrupted(db: AsyncSession, task: Task) -> None:
            if task.id == broken_id:
                raise RuntimeError("сбой прохода после commit первой задачи")
            await original(db, task)

        enqueued: list[str] = []
        monkeypatch.setattr(dispatcher_module, "ensure_task_launchable", interrupted)
        monkeypatch.setattr(
            run_task_session, "delay", lambda task_id, **_: enqueued.append(task_id)
        )

        with pytest.raises(RuntimeError, match="сбой прохода"):
            await periodic._dispatch(db_session)

        assert enqueued == [str(good_id)]
        await db_session.refresh(good)
        assert good.status is TaskStatus.QUEUED

    async def test_broker_failure_retried_next_pass(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _user(db_session)
        tasks = [await _queued(db_session, user) for _ in range(2)]
        ids = {str(task.id) for task in tasks}
        attempts: list[str] = []

        def unavailable(task_id: str, **_kwargs: object) -> None:
            attempts.append(task_id)
            raise OperationalError("брокер недоступен")

        monkeypatch.setattr(run_task_session, "delay", unavailable)
        with pytest.raises(OperationalError):
            await periodic._dispatch(db_session)
        assert set(attempts) == ids

        delivered: list[str] = []
        monkeypatch.setattr(
            run_task_session, "delay", lambda task_id, **_: delivered.append(task_id)
        )
        await periodic._dispatch(db_session)
        assert set(delivered) == ids

    async def test_manual_restart_not_recovered_as_new_launch(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = await _user(db_session)
        await make_task(
            db_session,
            created_by=user.id,
            status=TaskStatus.QUEUED,
            launched_manually=True,
            last_failed_order_index=2,
        )
        delivered: list[str] = []
        monkeypatch.setattr(
            run_task_session, "delay", lambda task_id, **_: delivered.append(task_id)
        )
        await periodic._dispatch(db_session)
        assert delivered == []
