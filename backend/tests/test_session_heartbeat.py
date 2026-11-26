"""Тесты `services/session_heartbeat.py` (раздел 6.6 ТЗ)."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest
import structlog
from redis.exceptions import ConnectionError

from db.models.enums import RemoteControlStatus, TaskStatus, UserRole
from db.models.tasks import Task
from db.models.users import User
from services import session_heartbeat
from services.notifications import NotificationEvent
from services.remote_control import check_session_bridges, check_task_bridge
from services.session_heartbeat import (
    SessionAlreadyOwnedError,
    beat,
    is_session_alive,
    keep_session_heartbeat,
    require_session_owner,
)
from services.task_control import consume_bridge_reconnect
from tests.factories import make_llm_account

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.usefixtures("postgres_container")
class TestSessionHeartbeat:
    async def test_alive_while_held_and_cleared_after(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()

        async with keep_session_heartbeat(redis_client, task_id, interval=0.05):
            assert await is_session_alive(redis_client, task_id)

        assert not await is_session_alive(redis_client, task_id)

    async def test_no_heartbeat(self, redis_client: Redis) -> None:
        assert not await is_session_alive(redis_client, uuid.uuid4())


@pytest.mark.usefixtures("postgres_container")
class TestSessionOwner:
    """Раздел 17.4: сессию задачи держит один исполнитель."""

    async def test_second_owner_rejected(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()

        async with keep_session_heartbeat(redis_client, task_id, interval=0.05):
            with pytest.raises(SessionAlreadyOwnedError):
                async with keep_session_heartbeat(redis_client, task_id, acquire_timeout=0.1):
                    pass
            assert await is_session_alive(redis_client, task_id)

    async def test_waits_for_release(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        released = asyncio.Event()

        async def first_owner() -> None:
            async with keep_session_heartbeat(redis_client, task_id):
                await asyncio.sleep(0.3)
            released.set()

        holder = asyncio.create_task(first_owner())
        await asyncio.sleep(0.05)
        async with keep_session_heartbeat(redis_client, task_id, acquire_timeout=5):
            assert released.is_set()
        await holder

    async def test_waits_for_old_owner_cleanup(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        reached = asyncio.Event()
        settling = asyncio.Event()
        finish_cleanup = asyncio.Event()

        async def old_owner() -> None:
            async with keep_session_heartbeat(redis_client, task_id, interval=0.02):
                reached.set()
                try:
                    await asyncio.Future()
                finally:
                    settling.set()
                    await finish_cleanup.wait()

        holder = asyncio.create_task(old_owner())
        try:
            await asyncio.wait_for(reached.wait(), timeout=2)
            await redis_client.delete(f"task:{task_id}:session-alive")
            await asyncio.wait_for(settling.wait(), timeout=2)
            with pytest.raises(SessionAlreadyOwnedError):
                async with keep_session_heartbeat(redis_client, task_id):
                    pytest.fail("Старый владелец ещё завершает работу")
            finish_cleanup.set()
            await asyncio.wait_for(holder, timeout=2)
            async with keep_session_heartbeat(redis_client, task_id):
                await require_session_owner()
        finally:
            finish_cleanup.set()
            holder.cancel()
            await asyncio.gather(holder, return_exceptions=True)

    async def test_hung_renewal_stops_owner(
        self, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def hung_renewal(*_args: object) -> bool:
            await asyncio.Future()
            return False

        monkeypatch.setattr(session_heartbeat, "HEARTBEAT_TTL_SECONDS", 1)
        monkeypatch.setattr(session_heartbeat, "_renew", hung_renewal)
        async with asyncio.timeout(2):
            async with keep_session_heartbeat(redis_client, uuid.uuid4(), interval=0.01):
                await asyncio.Future()

    async def test_hung_redis_cleanup_releases_postgres_lock(
        self, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        task_id = uuid.uuid4()
        commands = 0

        async def hung_eval(*_args: object) -> None:
            nonlocal commands
            commands += 1
            await asyncio.Future()

        with monkeypatch.context() as patch:
            patch.setattr(session_heartbeat, "HEARTBEAT_TTL_SECONDS", 1)
            patch.setattr(session_heartbeat, "_RELEASE_TIMEOUT_SECONDS", 0.05)
            patch.setattr(redis_client, "eval", hung_eval)
            async with asyncio.timeout(2):
                async with keep_session_heartbeat(redis_client, task_id, interval=0.01):
                    await asyncio.Future()

        assert commands == 2
        async with keep_session_heartbeat(redis_client, task_id):
            await require_session_owner()

    async def test_retries_temporary_redis_error(
        self, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original_get = redis_client.get
        calls = 0

        async def flaky_get(key: str) -> bytes | str | None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("temporary")
            value: bytes | str | None = await original_get(key)
            return value

        monkeypatch.setattr(redis_client, "get", flaky_get)
        async with keep_session_heartbeat(redis_client, uuid.uuid4()):
            await require_session_owner()
            assert calls == 2

    async def test_checks_token_before_work(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        executed = False
        async with keep_session_heartbeat(redis_client, task_id):
            await beat(redis_client, task_id)
            await require_session_owner()
            executed = True
        assert not executed
        assert await is_session_alive(redis_client, task_id)

    async def test_foreign_key_not_released(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        await beat(redis_client, task_id)

        with pytest.raises(SessionAlreadyOwnedError):
            async with keep_session_heartbeat(redis_client, task_id):
                pass

        assert await is_session_alive(redis_client, task_id)


class TestCheckTaskBridge:
    async def _task(
        self,
        db_session: AsyncSession,
        *,
        attempts: int,
        status: RemoteControlStatus,
        with_llm: bool = True,
    ) -> Task:
        user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
        db_session.add(user)
        await db_session.flush()
        account = await make_llm_account(db_session, owner_id=user.id) if with_llm else None
        task = Task(
            code=f"RR-{uuid.uuid4().hex[:5]}",
            title="t",
            description="d",
            created_by=user.id,
            llm_account_id=account.id if account else None,
            status=TaskStatus.IN_PROGRESS,
            remote_control_status=status,
            remote_control_reconnect_attempts=attempts,
        )
        db_session.add(task)
        # Перевод в `failed` откатывает транзакцию проверки — задача должна пережить откат.
        await db_session.commit()
        return task

    def _capture_events(self, monkeypatch: pytest.MonkeyPatch) -> list[NotificationEvent]:
        events: list[NotificationEvent] = []

        async def capture(_db: AsyncSession, *, event: NotificationEvent, **_: object) -> None:
            events.append(event)

        monkeypatch.setattr("services.remote_control.notify_task_event", capture)
        monkeypatch.setattr("services.task_status.notify_task_event", capture)
        return events

    async def test_alive_resets_attempts(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task = await self._task(db_session, attempts=1, status=RemoteControlStatus.CONNECTED)
        await beat(redis_client, task.id)

        await check_task_bridge(db_session, task=task, redis_client=redis_client)

        assert task.remote_control_reconnect_attempts == 0
        assert task.remote_control_status is RemoteControlStatus.CONNECTED
        assert await consume_bridge_reconnect(redis_client, task.id) is False

    async def test_two_attempts_then_disconnected_and_failed(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        events = self._capture_events(monkeypatch)
        task = await self._task(db_session, attempts=0, status=RemoteControlStatus.CONNECTED)

        observed: list[tuple[RemoteControlStatus, bool]] = []
        for _ in range(3):
            await check_task_bridge(db_session, task=task, redis_client=redis_client)
            observed.append(
                (task.remote_control_status, await consume_bridge_reconnect(redis_client, task.id)),
            )

        assert observed == [
            (RemoteControlStatus.RECONNECTING, True),
            (RemoteControlStatus.RECONNECTING, True),
            (RemoteControlStatus.DISCONNECTED, False),
        ]
        assert task.status is TaskStatus.FAILED
        assert events == [NotificationEvent.REMOTE_CONTROL_DISCONNECTED, NotificationEvent.FAILED]

    async def test_new_owner_prevents_failed_transition(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task = await self._task(db_session, attempts=2, status=RemoteControlStatus.CONNECTED)

        async def stale_observation(redis: Redis, task_id: uuid.UUID) -> bool:
            await beat(redis, task_id)
            return False

        monkeypatch.setattr("services.remote_control.is_session_alive", stale_observation)
        await check_task_bridge(db_session, task=task, redis_client=redis_client)

        assert task.status is TaskStatus.IN_PROGRESS
        assert await is_session_alive(redis_client, task.id)

    async def test_unavailable_bridge_fails_quietly(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Раздел 6.6: при `unavailable` мост не восстанавливается, о разрыве не сообщается."""
        events = self._capture_events(monkeypatch)
        task = await self._task(db_session, attempts=0, status=RemoteControlStatus.UNAVAILABLE)

        for _ in range(3):
            await check_task_bridge(db_session, task=task, redis_client=redis_client)
            assert await consume_bridge_reconnect(redis_client, task.id) is False

        assert (task.status, task.remote_control_status) == (
            TaskStatus.FAILED,
            RemoteControlStatus.UNAVAILABLE,
        )
        assert events == [NotificationEvent.FAILED]

    async def test_task_without_llm_fails_without_bridge(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        events = self._capture_events(monkeypatch)
        task = await self._task(
            db_session,
            attempts=0,
            status=RemoteControlStatus.CONNECTED,
            with_llm=False,
        )

        for _ in range(3):
            await check_task_bridge(db_session, task=task, redis_client=redis_client)
            assert await consume_bridge_reconnect(redis_client, task.id) is False

        assert task.status is TaskStatus.FAILED
        assert task.remote_control_status is RemoteControlStatus.CONNECTED
        assert events == [NotificationEvent.FAILED]


class TestCheckSessionBridges:
    @pytest.mark.parametrize("owner_alive", [False, True])
    async def test_requests_recovery_only_without_owner(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        owner_alive: bool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
        db_session.add(user)
        await db_session.flush()
        task = Task(
            code=f"RR-{uuid.uuid4().hex[:5]}",
            title="t",
            description="d",
            created_by=user.id,
            status=TaskStatus.PAUSED,
        )
        db_session.add(task)
        await db_session.flush()
        if owner_alive:
            await beat(redis_client, task.id)
        scheduled: list[str] = []
        observations: list[uuid.UUID] = []

        async def observe(redis: Redis, task_id: uuid.UUID) -> bool:
            observations.append(task_id)
            return await is_session_alive(redis, task_id)

        monkeypatch.setattr("services.remote_control.is_session_alive", observe)

        await check_session_bridges(
            db_session, redis_client=redis_client, schedule_paused_recovery=scheduled.append
        )
        assert scheduled == ([] if owner_alive else [str(task.id)])
        assert observations.count(task.id) == 1
        assert task.status is TaskStatus.PAUSED

    async def test_checks_every_session_status(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        checked: list[uuid.UUID] = []
        bound: list[object] = []

        async def record(
            _db: AsyncSession,
            *,
            task: Task,
            redis_client: Redis,
            schedule_paused_recovery: object = None,
        ) -> None:
            checked.append(task.id)
            bound.append(structlog.contextvars.get_contextvars().get("task_id"))

        monkeypatch.setattr("services.remote_control.check_task_bridge", record)
        user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
        db_session.add(user)
        await db_session.flush()
        tasks = {
            status: Task(
                code=f"RR-{uuid.uuid4().hex[:5]}",
                title="t",
                description="d",
                created_by=user.id,
                status=status,
            )
            for status in (TaskStatus.REBASE_CONFLICT, TaskStatus.PAUSED, TaskStatus.DONE)
        }
        db_session.add_all(tasks.values())
        await db_session.flush()

        await check_session_bridges(db_session, redis_client=redis_client)

        assert tasks[TaskStatus.REBASE_CONFLICT].id in checked
        assert tasks[TaskStatus.PAUSED].id in checked
        assert tasks[TaskStatus.DONE].id not in checked
        # Раздел 17.2: события проверки задачи — с её `task_id`.
        assert bound == [str(task_id) for task_id in checked]
