"""
Очередь задач пользователя и слоты параллельного запуска (раздел 14.4 ТЗ).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest

from db.models.enums import TaskStatus
from db.models.tasks import Task
from services.errors import ConflictError, ValidationError
from services.refining_chat import start_chat
from services.session_heartbeat import beat
from services.task_queue import (
    change_task_status_manually,
    moscow_cron,
    night_window_active,
    night_window_cron,
    occupied_slots,
    queue_positions,
    queue_summary,
    validate_night_window,
)
from services.task_status import transition_task_status
from tests.factories import make_task, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

_MSK_UTC_OFFSET = timedelta(hours=3)


def _msk(hour: int, minute: int = 0) -> datetime:
    """Момент по московскому времени, переданный как UTC."""
    return datetime(2026, 11, 9, hour, minute, tzinfo=UTC) - _MSK_UTC_OFFSET


class TestNightWindow:
    @pytest.mark.parametrize(
        ("moment", "start", "end", "inside"),
        [
            pytest.param(_msk(3, 15), time(3, 15), time(7, 0), True, id="начало включительно"),
            pytest.param(_msk(6, 59), time(3, 15), time(7, 0), True, id="внутри"),
            pytest.param(_msk(7, 0), time(3, 15), time(7, 0), False, id="конец не входит"),
            pytest.param(_msk(3, 14), time(3, 15), time(7, 0), False, id="до начала"),
            pytest.param(_msk(23, 30), time(23, 0), time(2, 0), True, id="через полночь до"),
            pytest.param(_msk(1, 0), time(23, 0), time(2, 0), True, id="через полночь после"),
            pytest.param(_msk(12, 0), time(23, 0), time(2, 0), False, id="через полночь днём"),
        ],
    )
    def test_active(self, moment: datetime, start: time, end: time, inside: bool) -> None:
        assert night_window_active(moment, start=start, end=end) is inside

    @pytest.mark.parametrize(
        ("start", "cron"),
        [
            pytest.param(time(3, 15), "15 0 * * *", id="по умолчанию"),
            pytest.param(time(0, 30), "30 21 * * *", id="на сутки назад"),
            pytest.param(time(23, 5), "5 20 * * *", id="вечер"),
        ],
    )
    def test_cron(self, start: time, cron: str) -> None:
        assert night_window_cron(start) == cron

    @pytest.mark.parametrize(
        ("at", "weekday", "cron"),
        [
            pytest.param(time(3, 0), None, "0 0 * * *", id="бэкап каждый день"),
            pytest.param(time(2, 0), 0, "0 23 * * 6", id="воскресенье на субботу UTC"),
            pytest.param(time(5, 0), 0, "0 2 * * 0", id="тот же день"),
            pytest.param(time(1, 30), 1, "30 22 * * 0", id="понедельник на воскресенье"),
        ],
    )
    def test_moscow_cron(self, at: time, weekday: int | None, cron: str) -> None:
        assert moscow_cron(at, weekday=weekday) == cron

    def test_equal_bounds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_night_window(start=time(3, 0), end=time(3, 0))


class TestOccupiedSlots:
    @pytest.mark.parametrize(
        ("status", "launched_manually", "occupies_slot", "occupied"),
        [
            pytest.param(TaskStatus.IN_PROGRESS, False, False, 1, id="из очереди"),
            pytest.param(TaskStatus.IN_PROGRESS, True, False, 0, id="вручную без галочки"),
            pytest.param(TaskStatus.IN_PROGRESS, True, True, 1, id="вручную с галочкой"),
            pytest.param(TaskStatus.QUEUED, False, False, 1, id="queued"),
            pytest.param(TaskStatus.AWAITING_INPUT, False, False, 1, id="ждёт решения"),
            pytest.param(TaskStatus.FAILED, False, False, 1, id="failed держит слот"),
            pytest.param(TaskStatus.DONE, False, False, 0, id="done освобождает"),
            pytest.param(TaskStatus.READY, False, True, 0, id="в очереди не занимает"),
            pytest.param(TaskStatus.REFINING, True, True, 0, id="уточняется без чата"),
        ],
    )
    async def test_by_status(
        self,
        *,
        db_session: AsyncSession,
        redis_client: Redis,
        status: TaskStatus,
        launched_manually: bool,
        occupies_slot: bool,
        occupied: int,
    ) -> None:
        task = await make_task(
            db_session,
            status=status,
            launched_manually=launched_manually,
            occupies_slot=occupies_slot,
        )

        counts = await occupied_slots(db_session, redis_client, [task.created_by])

        assert counts.get(task.created_by, 0) == occupied

    @pytest.mark.parametrize(
        ("from_status", "launched_manually", "occupied"),
        [
            pytest.param(TaskStatus.IN_PROGRESS, False, 1, id="из очереди"),
            pytest.param(TaskStatus.PAUSED, True, 0, id="вручную без галочки"),
            pytest.param(TaskStatus.REFINING, False, 0, id="из чата"),
        ],
    )
    async def test_limit_wait(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        from_status: TaskStatus,
        launched_manually: bool,
        occupied: int,
    ) -> None:
        task = await make_task(
            db_session,
            status=TaskStatus.AWAITING_LIMIT,
            limit_wait_from_status=from_status,
            launched_manually=launched_manually,
        )

        counts = await occupied_slots(db_session, redis_client, [task.created_by])

        assert counts.get(task.created_by, 0) == occupied

    @pytest.mark.parametrize(("occupies_slot", "occupied"), [(True, 1), (False, 0)])
    async def test_refining_chat(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        occupies_slot: bool,
        occupied: int,
    ) -> None:
        task = await make_task(
            db_session,
            status=TaskStatus.REFINING,
            launched_manually=True,
            occupies_slot=occupies_slot,
        )
        await beat(redis_client, task.id)

        counts = await occupied_slots(db_session, redis_client, [task.created_by])

        assert counts.get(task.created_by, 0) == occupied

    async def test_per_user(self, db_session: AsyncSession, redis_client: Redis) -> None:
        first = await make_task(db_session, status=TaskStatus.IN_PROGRESS)
        second = await make_task(db_session, status=TaskStatus.IN_PROGRESS)
        await make_task(db_session, status=TaskStatus.PAUSED, created_by=first.created_by)

        counts = await occupied_slots(
            db_session,
            redis_client,
            [first.created_by, second.created_by],
        )

        assert counts == {first.created_by: 2, second.created_by: 1}


async def _queued_task(
    db_session: AsyncSession,
    *,
    created_by: uuid.UUID,
    priority: int,
    minutes_ago: int,
    status: TaskStatus = TaskStatus.READY,
) -> Task:
    return await make_task(
        db_session,
        created_by=created_by,
        status=status,
        queue_priority=priority,
        ready_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


class TestQueuePositions:
    async def test_priority_then_time(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        older = await _queued_task(db_session, created_by=user.id, priority=100, minutes_ago=30)
        newer = await _queued_task(db_session, created_by=user.id, priority=100, minutes_ago=5)
        urgent = await _queued_task(
            db_session,
            created_by=user.id,
            priority=200,
            minutes_ago=1,
            status=TaskStatus.NIGHT_WORKER,
        )
        outside = await make_task(db_session, created_by=user.id, status=TaskStatus.DEFINED)

        positions = await queue_positions(
            db_session,
            [older.id, newer.id, urgent.id, outside.id],
        )

        assert positions == {urgent.id: 1, older.id: 2, newer.id: 3}

    async def test_per_author(self, db_session: AsyncSession) -> None:
        first = await _queued_task(
            db_session,
            created_by=(await make_user(db_session)).id,
            priority=100,
            minutes_ago=10,
        )
        second = await _queued_task(
            db_session,
            created_by=(await make_user(db_session)).id,
            priority=100,
            minutes_ago=20,
        )

        assert await queue_positions(db_session, [first.id, second.id]) == {
            first.id: 1,
            second.id: 1,
        }

    async def test_empty(self, db_session: AsyncSession) -> None:
        assert await queue_positions(db_session, []) == {}


class TestQueueSummary:
    async def test_counts(self, db_session: AsyncSession, redis_client: Redis) -> None:
        user = await make_user(db_session)
        await make_task(db_session, created_by=user.id, status=TaskStatus.IN_PROGRESS)
        for status in (TaskStatus.READY, TaskStatus.READY, TaskStatus.NIGHT_WORKER):
            await make_task(db_session, created_by=user.id, status=status)

        summary = await queue_summary(
            db_session,
            redis_client,
            user_id=user.id,
            max_parallel_tasks=3,
        )

        assert (summary.occupied, summary.ready, summary.night_worker) == (1, 2, 1)


class TestManualStatusChange:
    @pytest.mark.parametrize(
        ("from_status", "to_status"),
        [
            (TaskStatus.NEW, TaskStatus.REFINING),
            (TaskStatus.REFINING, TaskStatus.DEFINED),
            (TaskStatus.DEFINED, TaskStatus.READY),
            (TaskStatus.READY, TaskStatus.NIGHT_WORKER),
            (TaskStatus.NIGHT_WORKER, TaskStatus.NEW),
        ],
    )
    async def test_between_pre_launch(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        from_status: TaskStatus,
        to_status: TaskStatus,
    ) -> None:
        task = await make_task(db_session, status=from_status)

        updated = await change_task_status_manually(
            db_session,
            redis_client,
            task=task,
            to_status=to_status,
        )

        assert updated.status is to_status

    @pytest.mark.parametrize(
        ("from_status", "to_status", "queued"),
        [
            pytest.param(TaskStatus.DEFINED, TaskStatus.READY, True, id="вход в очередь"),
            pytest.param(TaskStatus.READY, TaskStatus.DEFINED, False, id="выход из очереди"),
        ],
    )
    async def test_ready_at(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        from_status: TaskStatus,
        to_status: TaskStatus,
        queued: bool,
    ) -> None:
        task = await make_task(db_session, status=from_status, ready_at=datetime.now(UTC))

        updated = await change_task_status_manually(
            db_session,
            redis_client,
            task=task,
            to_status=to_status,
        )

        assert (updated.ready_at is not None) is queued

    async def test_between_queues_keeps_place(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        ready_at = datetime.now(UTC) - timedelta(hours=1)
        task = await make_task(db_session, status=TaskStatus.READY, ready_at=ready_at)

        updated = await change_task_status_manually(
            db_session,
            redis_client,
            task=task,
            to_status=TaskStatus.NIGHT_WORKER,
        )

        assert updated.ready_at == ready_at

    @pytest.mark.parametrize("from_status", [TaskStatus.FAILED, TaskStatus.DONE])
    async def test_from_terminal_resets_run(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        from_status: TaskStatus,
    ) -> None:
        task = await make_task(
            db_session,
            status=from_status,
            last_failed_order_index=2,
            auto_start_enabled=True,
        )

        updated = await change_task_status_manually(
            db_session,
            redis_client,
            task=task,
            to_status=TaskStatus.READY,
        )

        assert updated.status is TaskStatus.READY
        assert (updated.last_failed_order_index, updated.auto_start_enabled) == (None, False)
        assert updated.reset_at is not None
        assert updated.ready_at is not None

    @pytest.mark.parametrize(
        ("from_status", "to_status", "error"),
        [
            pytest.param(TaskStatus.IN_PROGRESS, TaskStatus.NEW, ConflictError, id="в работе"),
            pytest.param(TaskStatus.QUEUED, TaskStatus.READY, ConflictError, id="queued"),
            pytest.param(TaskStatus.NEW, TaskStatus.QUEUED, ValidationError, id="в queued"),
            pytest.param(TaskStatus.FAILED, TaskStatus.DONE, ValidationError, id="в done"),
        ],
    )
    async def test_rejected(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        from_status: TaskStatus,
        to_status: TaskStatus,
        error: type[Exception],
    ) -> None:
        task = await make_task(db_session, status=from_status)

        with pytest.raises(error):
            await change_task_status_manually(
                db_session,
                redis_client,
                task=task,
                to_status=to_status,
            )

    async def test_refining_chat_running(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task = await make_task(db_session, status=TaskStatus.REFINING)
        await beat(redis_client, task.id)

        with pytest.raises(ConflictError):
            await change_task_status_manually(
                db_session,
                redis_client,
                task=task,
                to_status=TaskStatus.DEFINED,
            )

    async def test_same_status_noop(self, db_session: AsyncSession, redis_client: Redis) -> None:
        task = await make_task(db_session, status=TaskStatus.DEFINED)

        updated = await change_task_status_manually(
            db_session,
            redis_client,
            task=task,
            to_status=TaskStatus.DEFINED,
        )

        assert updated.status is TaskStatus.DEFINED


@pytest.mark.parametrize("target", [TaskStatus.READY, TaskStatus.DEFINED, TaskStatus.QUEUED])
async def test_status_cas_rechecks_chat_flag(
    db_session: AsyncSession,
    target: TaskStatus,
) -> None:
    task = await make_task(db_session, status=TaskStatus.REFINING)
    await start_chat(db_session, task_id=task.id)
    with pytest.raises(ConflictError):
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=TaskStatus.REFINING,
            to_status=target,
        )
    await db_session.refresh(task)
    assert (task.status, task.chat_active) == (TaskStatus.REFINING, True)
