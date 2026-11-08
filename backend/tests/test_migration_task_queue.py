"""
Миграция `a3f9d2c71e58`: статусы задачи до запуска, поля очереди, лимит
пользователя и ночное окно. Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import uuid
from datetime import time

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "f2c7a9d4e815"
_REVISION = "a3f9d2c71e58"
_NEW_STATUSES = ("refining", "defined", "ready", "night_worker")


async def _seed_task(engine: AsyncEngine) -> uuid.UUID:
    user_id, task_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO users (id, email, role, is_active) "
                "VALUES (:id, :email, 'user', true)",
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        await connection.execute(
            sa.text(
                "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
                "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
                "auto_start_enabled, created_by) VALUES (:id, :code, 't', 'd', 'new', false, "
                "false, 'unavailable', 0, false, :user_id)",
            ),
            {"id": task_id, "code": f"RR-{task_id.hex[:8]}", "user_id": user_id},
        )
    return task_id


async def _scalar(engine: AsyncEngine, query: str) -> object:
    async with engine.connect() as connection:
        return (await connection.execute(sa.text(query))).scalar_one()


class TestTaskQueueMigration:
    async def test_defaults(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            await _seed_task(engine)
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                task = (
                    await connection.execute(
                        sa.text(
                            "SELECT queue_priority, ready_at, occupies_slot, launched_manually, "
                            "queued_from_status FROM tasks",
                        ),
                    )
                ).one()
                limit = (
                    await connection.execute(sa.text("SELECT max_parallel_tasks FROM users"))
                ).scalar_one()
                labels = set(
                    (
                        await connection.execute(
                            sa.text("SELECT unnest(enum_range(NULL::task_status))::text"),
                        )
                    ).scalars(),
                )
            column_default = await _scalar(
                engine,
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'system_settings' AND column_name = 'night_window_start'",
            )
        finally:
            await engine.dispose()
        assert tuple(task) == (100, None, False, False, None)
        assert limit == 3
        assert set(_NEW_STATUSES) <= labels
        assert "03:15" in str(column_default)

    async def test_repeated_upgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        run_alembic(scratch_database, "upgrade", _REVISION)
        engine = create_async_engine(scratch_database)
        try:
            night_end = await _scalar(
                engine,
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'system_settings' AND column_name = 'night_window_end'",
            )
        finally:
            await engine.dispose()
        assert str(time(7, 0)) in str(night_end)

    @pytest.mark.parametrize("status", _NEW_STATUSES)
    async def test_downgrade_restores_new(self, scratch_database: str, status: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            task_id = await _seed_task(engine)
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text("UPDATE tasks SET status = :status WHERE id = :id"),
                    {"status": status, "id": task_id},
                )
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            async with engine.connect() as connection:
                restored = (
                    await connection.execute(sa.text("SELECT status::text FROM tasks"))
                ).scalar_one()
                columns = set(
                    (
                        await connection.execute(
                            sa.text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_name IN ('tasks', 'users', 'system_settings')",
                            ),
                        )
                    ).scalars(),
                )
        finally:
            await engine.dispose()
        assert restored == "new"
        assert not columns & {
            "queue_priority",
            "ready_at",
            "occupies_slot",
            "launched_manually",
            "queued_from_status",
            "max_parallel_tasks",
            "night_window_start",
            "night_window_end",
        }
