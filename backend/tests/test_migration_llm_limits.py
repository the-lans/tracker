"""
Миграция `e5b81c4d2f97`: ожидание лимита, окно и стоимость хода аккаунта,
сжатие контекста в профиле. Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "c7e4b19a3d60"
_REVISION = "e5b81c4d2f97"
_NEW_COLUMNS = {
    "limit_wait_from_status",
    "limit_wait_until",
    "limit_wait_order_index",
    "window_started_at",
    "turn_cost_pct",
    "llm_compact_on_switch",
}


async def _seed_task(engine: AsyncEngine) -> uuid.UUID:
    user_id, task_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)",
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        await connection.execute(
            sa.text(
                "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
                "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
                "auto_start_enabled, created_by, last_failed_order_index) VALUES (:id, :code, "
                "'t', 'd', 'new', false, false, 'unavailable', 0, false, :user_id, 1)",
            ),
            {"id": task_id, "code": f"RR-{task_id.hex[:8]}", "user_id": user_id},
        )
    return task_id


async def _labels(engine: AsyncEngine, enum_name: str) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text(f"SELECT unnest(enum_range(NULL::{enum_name}))::text"),
        )
        return set(rows.scalars())


async def _columns(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name IN ('tasks', 'llm_accounts', 'users')",
            ),
        )
        return set(rows.scalars())


class TestLlmLimitMigration:
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
                            "SELECT limit_wait_from_status, limit_wait_until, "
                            "limit_wait_order_index FROM tasks",
                        ),
                    )
                ).one()
                compact = (
                    await connection.execute(sa.text("SELECT llm_compact_on_switch FROM users"))
                ).scalar_one()
            statuses = await _labels(engine, "task_status")
            reasons = await _labels(engine, "llm_switch_reason")
            columns = await _columns(engine)
        finally:
            await engine.dispose()
        assert tuple(task) == (None, None, None)
        assert compact is True
        assert "awaiting_limit" in statuses
        assert {"window_planned", "window_balance", "week_exhausted"} <= reasons
        assert _NEW_COLUMNS <= columns
        # Недельный порог читает прежняя версия — столбец остаётся.
        assert "llm_switch_threshold_week_pct" in columns

    async def test_repeated_upgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        run_alembic(scratch_database, "upgrade", _REVISION)
        engine = create_async_engine(scratch_database)
        try:
            columns = await _columns(engine)
        finally:
            await engine.dispose()
        assert _NEW_COLUMNS <= columns

    @pytest.mark.parametrize(
        ("from_status", "expected_status", "expected_restart"),
        [
            ("in_progress", "failed", 4),
            ("paused", "failed", 4),
            ("refining", "refining", 1),
        ],
    )
    async def test_downgrade_restores_waits(
        self,
        scratch_database: str,
        from_status: str,
        expected_status: str,
        expected_restart: int,
    ) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            task_id = await _seed_task(engine)
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "UPDATE tasks SET status = 'awaiting_limit', "
                        "limit_wait_from_status = CAST(:from_status AS task_status), "
                        "limit_wait_order_index = 4 WHERE id = :id",
                    ),
                    {"from_status": from_status, "id": task_id},
                )
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            async with engine.connect() as connection:
                restored = (
                    await connection.execute(
                        sa.text("SELECT status::text, last_failed_order_index FROM tasks"),
                    )
                ).one()
            columns = await _columns(engine)
        finally:
            await engine.dispose()
        assert tuple(restored) == (expected_status, expected_restart)
        assert not columns & _NEW_COLUMNS
