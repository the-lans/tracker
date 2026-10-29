"""Тесты `services/session_heartbeat.py` (раздел 6.6 ТЗ)."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import pytest
import structlog

from db.models.enums import RemoteControlStatus, TaskStatus, UserRole
from db.models.tasks import Task
from db.models.users import User
from services.notifications import NotificationEvent
from services.remote_control import check_session_bridges, check_task_bridge
from services.session_heartbeat import (
    SessionAlreadyOwnedError,
    beat,
    is_session_alive,
    keep_session_heartbeat,
)
from services.task_control import consume_bridge_reconnect
from tests.factories import make_llm_account

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession


class TestSessionHeartbeat:
    async def test_alive_while_held_and_cleared_after(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()

        async with keep_session_heartbeat(redis_client, task_id, interval=0.05):
            assert await is_session_alive(redis_client, task_id)

        assert not await is_session_alive(redis_client, task_id)

    async def test_no_heartbeat(self, redis_client: Redis) -> None:
        assert not await is_session_alive(redis_client, uuid.uuid4())


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
    async def test_checks_every_session_status(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        checked: list[uuid.UUID] = []
        bound: list[object] = []

        async def record(_db: AsyncSession, *, task: Task, redis_client: Redis) -> None:
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
