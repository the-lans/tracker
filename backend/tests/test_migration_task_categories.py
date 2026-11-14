"""
Миграция `d8a3f6c1b742`: категории задач (раздел 15.7). Проверяется на
отдельной временной базе.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "d2b7f4a9c613"
_REVISION = "d8a3f6c1b742"
_USER_INSERT = (
    "INSERT INTO users (id, email, role, is_active) VALUES (:id, 'qa@example.com', 'user', true)"
)
_CATEGORY_INSERT = (
    "INSERT INTO task_categories (id, name, created_by) VALUES (:id, 'Бэкенд', :user_id)"
)
_TASK_INSERT = (
    "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
    "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
    "auto_start_enabled, created_by, category_id) VALUES (:id, 'RR-1', 't', 'd', 'new', "
    "false, false, 'unavailable', 0, false, :user_id, :category_id)"
)


async def _schema_objects(engine: AsyncEngine) -> tuple[bool, bool, bool]:
    async with engine.connect() as connection:
        categories = await connection.execute(sa.text("SELECT to_regclass('task_categories')"))
        prompts = await connection.execute(
            sa.text("SELECT to_regclass('task_category_library_prompts')"),
        )
        column = await connection.execute(
            sa.text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'tasks' AND column_name = 'category_id'",
            ),
        )
        return (
            categories.scalar_one() is not None,
            prompts.scalar_one() is not None,
            column.scalar_one() == 1,
        )


@pytest.fixture
async def engine(scratch_database: str) -> AsyncEngine:
    run_alembic(scratch_database, "upgrade", _REVISION)
    return create_async_engine(scratch_database)


class TestTaskCategoriesMigration:
    async def test_repeated_upgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert await _schema_objects(engine) == (False, False, False)
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert await _schema_objects(engine) == (True, True, True)
        finally:
            await engine.dispose()

    async def test_deleted_category_leaves_task(self, engine: AsyncEngine) -> None:
        user_id, category_id, task_id = (uuid.uuid4() for _ in range(3))
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(_USER_INSERT), {"id": user_id})
                await connection.execute(
                    sa.text(_CATEGORY_INSERT),
                    {"id": category_id, "user_id": user_id},
                )
                await connection.execute(
                    sa.text(_TASK_INSERT),
                    {"id": task_id, "user_id": user_id, "category_id": category_id},
                )
                await connection.execute(
                    sa.text("DELETE FROM task_categories WHERE id = :id"),
                    {"id": category_id},
                )
                stored = await connection.scalar(
                    sa.text("SELECT category_id FROM tasks WHERE id = :id"),
                    {"id": task_id},
                )
            assert stored is None
        finally:
            await engine.dispose()
