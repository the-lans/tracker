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

import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from db.models.enums import TaskStatus, UserRole
from db.models.tasks import Task
from db.models.users import User
from db.session import async_session_factory
from ws.tasks import _fetch_status


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


async def test_fetch_status_returns_none_for_unknown_task() -> None:
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
