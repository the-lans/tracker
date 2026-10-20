"""`/ws/tasks/{task_id}/status` (раздел 18.1 ТЗ).

Проверки авторизации (без токена / с недействительным токеном) не касаются
БД — они безопасно проверяются через `TestClient.websocket_connect`
(отдельный event loop `anyio`-портала), в отличие от `_fetch_status`,
использующего `db.session.async_session_factory` — тестируется напрямую
как обычная async-функция в event loop'е `pytest-asyncio`, чтобы не
столкнуться с привязкой asyncpg-соединений к loop'у (см.
`conftest.py::db_session`); данные для неё коммитятся через тот же
`async_session_factory`, а не через `db_session`-фикстуру, чей rollback
после теста не виден другому соединению.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from starlette.websockets import WebSocketDisconnect

from db.models.enums import TaskStatus, UserRole
from db.models.tasks import Task
from db.models.users import User
from db.session import async_session_factory
from services.output_stream import output_channel_name, publish_output_delta
from ws.tasks import _fetch_status, serve_task_events, stream_task_events


def test_rejects_connection_without_token() -> None:
    from main import app

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app).websocket_connect(f"/ws/tasks/{uuid.uuid4()}/status"),
    ):
        pass

    assert exc_info.value.code == 4401


def test_rejects_connection_with_invalid_token() -> None:
    from main import app

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        TestClient(app).websocket_connect(
            f"/ws/tasks/{uuid.uuid4()}/status?token=not-a-real-token",
        ),
    ):
        pass

    assert exc_info.value.code == 4401


async def test_fetch_status_returns_none_for_unknown_task(run_migrations: None) -> None:
    assert await _fetch_status(uuid.uuid4()) is None


async def test_fetch_status_returns_current_status(run_migrations: None) -> None:
    """`_fetch_status` читает через `db.session.async_session_factory`
    (реальный, отдельный от `db_session`-фикстуры пул соединений) — фикстура
    `db_session` оборачивает изменения в транзакцию, которая откатывается
    после теста и потому НИКОГДА не видна из другого соединения (см.
    docstring модуля). Здесь строка коммитится по-настоящему через тот же
    `async_session_factory`, которым пользуется сам `_fetch_status`, и
    удаляется вручную по завершении теста."""
    user_id = uuid.uuid4()
    task_id = uuid.uuid4()
    async with async_session_factory() as session:
        session.add(
            User(id=user_id, email=f"{task_id}@example.com", role=UserRole.ADMIN, is_active=True),
        )
        await session.commit()
        session.add(
            Task(
                id=task_id,
                code=f"RR-{task_id.hex[:8]}",
                title="Задача для WS",
                description="",
                status=TaskStatus.IN_PROGRESS,
                created_by=user_id,
            ),
        )
        await session.commit()

    try:
        status = await _fetch_status(task_id)
        assert status is TaskStatus.IN_PROGRESS
    finally:
        async with async_session_factory() as session:
            task = await session.get(Task, task_id)
            if task is not None:
                await session.delete(task)
            user = await session.get(User, user_id)
            if user is not None:
                await session.delete(user)
            await session.commit()


class TestStreamTaskEvents:
    async def test_forwards_status_and_output(self, redis_client: Redis) -> None:
        task_id = uuid.uuid4()
        node_log_id = uuid.uuid4()
        statuses = [TaskStatus.IN_PROGRESS, TaskStatus.IN_PROGRESS, TaskStatus.PLAN_REVIEW]
        sent: list[dict[str, Any]] = []
        received_status = asyncio.Event()

        async def fetch_status(_task_id: uuid.UUID) -> TaskStatus | None:
            return statuses.pop(0) if statuses else None

        async def send(payload: dict[str, Any]) -> None:
            sent.append(payload)
            received_status.set()

        streaming = asyncio.create_task(
            stream_task_events(
                send,
                task_id=task_id,
                redis_client=redis_client,
                fetch_status=fetch_status,
            ),
        )
        await asyncio.wait_for(received_status.wait(), timeout=5)
        await publish_output_delta(
            redis_client,
            task_id=task_id,
            node_log_id=node_log_id,
            text="Привет",
        )
        await asyncio.wait_for(streaming, timeout=10)

        assert sent == [
            {"type": "status", "task_id": str(task_id), "status": "in_progress"},
            {"type": "output_delta", "node_log_id": str(node_log_id), "text": "Привет"},
            {"type": "status", "task_id": str(task_id), "status": "plan_review"},
        ]


class TestServeTaskEvents:
    async def test_client_disconnect_releases_subscription(self, redis_client: Redis) -> None:
        """Задача не меняется, отправлять нечего — закрытие вкладки всё равно
        освобождает подписку Redis."""
        task_id = uuid.uuid4()
        closed = asyncio.Event()

        class IdleClient:
            sent: list[dict[str, Any]] = []

            async def send_json(self, payload: dict[str, Any]) -> None:
                self.sent.append(payload)

            async def receive(self) -> dict[str, Any]:
                await closed.wait()
                return {"type": "websocket.disconnect", "code": 1001}

            async def close(self, code: int) -> None:
                raise AssertionError(f"сокет уже закрыт клиентом, close({code}) не нужен")

        async def fetch_status(_task_id: uuid.UUID) -> TaskStatus | None:
            return TaskStatus.DONE

        serving = asyncio.create_task(
            serve_task_events(
                IdleClient(),  # type: ignore[arg-type]
                task_id=task_id,
                redis_client=redis_client,
                fetch_status=fetch_status,
            ),
        )
        channel = output_channel_name(task_id)
        for _ in range(50):
            if dict(await redis_client.pubsub_numsub(channel)).get(channel.encode()):
                break
            await asyncio.sleep(0.05)
        assert dict(await redis_client.pubsub_numsub(channel))[channel.encode()] == 1

        closed.set()
        await asyncio.wait_for(serving, timeout=5)

        assert dict(await redis_client.pubsub_numsub(channel))[channel.encode()] == 0
