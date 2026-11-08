"""Флаг обслуживания на время обновления сервера (раздел 20.6 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from db.models.enums import TaskStatus
from services.autostart import run_scheduled_autostart_check
from services.maintenance import MAINTENANCE_KEY, MAINTENANCE_MESSAGE, maintenance_active
from tasks import session_worker
from tests.factories import make_pipeline, make_task, make_user
from tests.worker_support import install_worker_env

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task
    from db.models.users import User

_FLAG_TTL_SECONDS = 600


async def _task(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    status: TaskStatus = TaskStatus.NEW,
    **fields: object,
) -> Task:
    pipeline = await make_pipeline(db_session, created_by=owner_id)
    return await make_task(
        db_session,
        created_by=owner_id,
        pipeline_id=pipeline.id,
        status=status,
        **fields,
    )


@pytest.fixture
async def maintenance(redis_client: Redis) -> None:
    await redis_client.set(MAINTENANCE_KEY, "1", ex=_FLAG_TTL_SECONDS)


class TestFlag:
    @pytest.mark.parametrize("flag_set", [True, False])
    async def test_read(self, redis_client: Redis, flag_set: bool) -> None:
        if flag_set:
            await redis_client.set(MAINTENANCE_KEY, "1", ex=_FLAG_TTL_SECONDS)

        assert await maintenance_active(redis_client) is flag_set

    async def test_redis_down_does_not_block(self) -> None:
        async def broken(_key: str) -> int:
            raise RedisConnectionError

        assert await maintenance_active(SimpleNamespace(exists=broken)) is False  # type: ignore[arg-type]


@pytest.mark.usefixtures("maintenance")
class TestLaunchApi:
    @pytest.mark.parametrize("action", ["start", "restart"])
    async def test_refused(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        action: str,
    ) -> None:
        status = TaskStatus.NEW if action == "start" else TaskStatus.FAILED
        task = await _task(db_session, current_user.id, status=status, last_failed_order_index=0)
        enqueued: list[object] = []
        monkeypatch.setattr(
            "api.tasks.lifecycle.run_task_session",
            SimpleNamespace(delay=lambda *args, **_: enqueued.append(args)),
        )

        response = await authed_client.post(f"/tasks/{task.id}/{action}")

        assert response.status_code == 503
        assert response.json()["error"]["message"] == MAINTENANCE_MESSAGE
        await db_session.refresh(task)
        assert (task.status, enqueued) == (status, [])


class TestAutostart:
    async def test_deferred_quietly(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        maintenance: None,
    ) -> None:
        notified: list[object] = []

        async def record(*_: object, **kwargs: object) -> None:
            notified.append(kwargs)

        monkeypatch.setattr("services.autostart.notify_task_event", record)
        now = datetime.now(UTC)
        owner = await make_user(db_session)
        task = await _task(
            db_session,
            owner.id,
            auto_start_enabled=True,
            scheduled_start_at=now - timedelta(minutes=1),
        )

        result = await run_scheduled_autostart_check(db_session, now=now)

        await db_session.refresh(task)
        assert (result.queued_task_ids, result.failed_task_ids) == ([], [])
        assert (task.status, notified) == (TaskStatus.NEW, [])


@pytest.mark.usefixtures("maintenance")
class TestWorker:
    @pytest.mark.parametrize(
        ("continuation", "deferred"),
        [(False, True), (True, False)],
        ids=["claim", "continuation"],
    )
    @pytest.mark.parametrize("queued_only", [False, True])
    async def test_queued_not_claimed(
        self,
        *,
        db_session: AsyncSession,
        redis_client: Redis,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        continuation: bool,
        deferred: bool,
        queued_only: bool,
    ) -> None:
        env = install_worker_env(
            db_session=db_session,
            redis_client=redis_client,
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
        owner = await make_user(db_session)
        task = await _task(db_session, owner.id, status=TaskStatus.QUEUED)

        await session_worker._run_task_session_async(
            task.id,
            start_after_order_index=None,
            continuation=continuation,
            queued_only=queued_only,
        )

        await db_session.refresh(task)
        assert task.status is TaskStatus.QUEUED
        kwargs = {"start_after_order_index": None, "continuation": False, "chat_only": False}
        if queued_only:
            kwargs["queued_only"] = True
        expected = [([str(task.id)], kwargs)]
        assert env.enqueued == (expected if deferred else [])
