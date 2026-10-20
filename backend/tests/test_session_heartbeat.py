"""Тесты `services/session_heartbeat.py` (раздел 6.6 ТЗ)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from db.models.enums import RemoteControlStatus, TaskStatus, UserRole
from db.models.tasks import Task
from db.models.users import User
from services.notifications import NotificationEvent
from services.remote_control import check_task_bridge
from services.session_heartbeat import beat, is_session_alive, keep_session_heartbeat
from services.task_control import consume_bridge_reconnect

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


class TestCheckTaskBridge:
    async def _task(
        self,
        db_session: AsyncSession,
        *,
        attempts: int,
        status: RemoteControlStatus,
    ) -> Task:
        user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
        db_session.add(user)
        await db_session.flush()
        task = Task(
            code=f"RR-{uuid.uuid4().hex[:5]}",
            title="t",
            description="d",
            created_by=user.id,
            status=TaskStatus.IN_PROGRESS,
            remote_control_status=status,
            remote_control_reconnect_attempts=attempts,
        )
        db_session.add(task)
        await db_session.flush()
        return task

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

    async def test_two_attempts_then_disconnected_once(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        events: list[NotificationEvent] = []

        async def capture(_db: AsyncSession, *, event: NotificationEvent, **_: object) -> None:
            events.append(event)

        monkeypatch.setattr("services.remote_control.notify_task_event", capture)
        task = await self._task(db_session, attempts=0, status=RemoteControlStatus.CONNECTED)

        observed: list[tuple[RemoteControlStatus, bool]] = []
        for _ in range(4):
            await check_task_bridge(db_session, task=task, redis_client=redis_client)
            observed.append(
                (task.remote_control_status, await consume_bridge_reconnect(redis_client, task.id)),
            )

        assert observed == [
            (RemoteControlStatus.RECONNECTING, True),
            (RemoteControlStatus.RECONNECTING, True),
            (RemoteControlStatus.DISCONNECTED, False),
            (RemoteControlStatus.DISCONNECTED, False),
        ]
        assert events == [NotificationEvent.REMOTE_CONTROL_DISCONNECTED]
