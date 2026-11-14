"""
Миграция `e5c9a3d7f142`: «Дейли» (разделы 3.1, 15.8, 19.8). Проверяется на
отдельной временной базе.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "b7d4e2a9c615"
_REVISION = "e5c9a3d7f142"
_TABLES = (
    "task_day_marks",
    "daily_events",
    "daily_plans",
    "daily_plan_templates",
    "google_calendar_connections",
)
_USER_INSERT = "INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)"
_SETTINGS_INSERT = (
    "INSERT INTO system_settings (id, default_timeout_seconds, default_max_retries, "
    "default_retry_base_delay_seconds, default_runner_image_python, default_runner_image_bash) "
    "VALUES (1, 600, 3, 5, 'python', 'bash') ON CONFLICT (id) DO NOTHING"
)
_TASK_INSERT = (
    "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
    "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
    "auto_start_enabled, created_by) VALUES (:id, :code, 't', 'd', 'new', "
    "false, false, 'unavailable', 0, false, :user_id)"
)
_MARK_INSERT = (
    "INSERT INTO task_day_marks (id, user_id, task_id, day) VALUES (:id, :user_id, :task_id, :day)"
)
_GOOGLE_EVENT_INSERT = (
    "INSERT INTO daily_events (id, user_id, source, day, end_day, title, calendar_id, "
    "external_id) VALUES (:id, :user_id, 'google', :day, :day, 'Созвон', 'primary', 'evt-1')"
)


async def _existing_tables(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text("SELECT tablename FROM pg_tables WHERE tablename = ANY(:names)"),
            {"names": list(_TABLES)},
        )
        return set(rows.scalars())


async def _seed_user_and_task(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    user_id, task_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(_USER_INSERT),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        await connection.execute(
            sa.text(_TASK_INSERT),
            {"id": task_id, "code": f"RR-{task_id.hex[:6]}", "user_id": user_id},
        )
    return user_id, task_id


@pytest.fixture
async def engine(scratch_database: str) -> AsyncEngine:
    run_alembic(scratch_database, "upgrade", _REVISION)
    return create_async_engine(scratch_database)


class TestDailyPlansMigration:
    async def test_repeated_upgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert await _existing_tables(engine) == set()
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert await _existing_tables(engine) == set(_TABLES)
        finally:
            await engine.dispose()

    async def test_existing_settings_get_day_start(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(_SETTINGS_INSERT))
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                value = await connection.scalar(
                    sa.text("SELECT day_start_time FROM system_settings WHERE id = 1"),
                )
            assert value == time(8, 0)
        finally:
            await engine.dispose()

    async def test_mark_unique_per_day(self, engine: AsyncEngine) -> None:
        try:
            user_id, task_id = await _seed_user_and_task(engine)
            params = {"user_id": user_id, "task_id": task_id, "day": date(2026, 11, 16)}
            async with engine.begin() as connection:
                await connection.execute(sa.text(_MARK_INSERT), {"id": uuid.uuid4(), **params})
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        sa.text(_MARK_INSERT),
                        {"id": uuid.uuid4(), **params},
                    )
        finally:
            await engine.dispose()

    async def test_deleted_task_drops_marks(self, engine: AsyncEngine) -> None:
        try:
            user_id, task_id = await _seed_user_and_task(engine)
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(_MARK_INSERT),
                    {
                        "id": uuid.uuid4(),
                        "user_id": user_id,
                        "task_id": task_id,
                        "day": date(2026, 11, 16),
                    },
                )
                await connection.execute(
                    sa.text("DELETE FROM tasks WHERE id = :id"),
                    {"id": task_id},
                )
                remaining = await connection.scalar(sa.text("SELECT count(*) FROM task_day_marks"))
            assert remaining == 0
        finally:
            await engine.dispose()

    async def test_google_event_unique(self, engine: AsyncEngine) -> None:
        try:
            user_id, _ = await _seed_user_and_task(engine)
            params = {"user_id": user_id, "day": date(2026, 11, 16)}
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(_GOOGLE_EVENT_INSERT),
                    {"id": uuid.uuid4(), **params},
                )
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        sa.text(_GOOGLE_EVENT_INSERT),
                        {"id": uuid.uuid4(), **params},
                    )
        finally:
            await engine.dispose()
