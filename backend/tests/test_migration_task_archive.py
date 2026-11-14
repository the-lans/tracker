"""
Миграция `f3a8c5e1d927`: архив задач (раздел 14.2). Проверяется на отдельной
временной базе.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "d8a3f6c1b742"
_REVISION = "f3a8c5e1d927"
_TASK_COLUMNS = {"finished_at", "archived_at", "archived_from_status"}
_USER_COLUMNS = {"archive_after_days", "cleanup_repos_after_days"}
_USER_INSERT = (
    "INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)"
)
_TASK_INSERT = (
    "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
    "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
    "auto_start_enabled, created_by) VALUES (:id, :code, 't', 'd', :status, false, false, "
    "'unavailable', 0, false, :user_id)"
)


async def _columns(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = :table"),
            {"table": table},
        )
        return set(rows.scalars())


async def _seed(engine: AsyncEngine, statuses: list[str]) -> tuple[uuid.UUID, list[uuid.UUID]]:
    user_id = uuid.uuid4()
    task_ids = [uuid.uuid4() for _ in statuses]
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(_USER_INSERT),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
        for task_id, status in zip(task_ids, statuses, strict=True):
            await connection.execute(
                sa.text(_TASK_INSERT),
                {
                    "id": task_id,
                    "code": f"RR-{task_id.hex[:8]}",
                    "status": status,
                    "user_id": user_id,
                },
            )
    return user_id, task_ids


@pytest.fixture
async def engine(scratch_database: str) -> AsyncEngine:
    run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
    return create_async_engine(scratch_database)


class TestTaskArchiveMigration:
    async def test_repeated_upgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert not _TASK_COLUMNS & await _columns(engine, "tasks")
            assert not _USER_COLUMNS & await _columns(engine, "users")
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert _TASK_COLUMNS <= await _columns(engine, "tasks")
            assert _USER_COLUMNS <= await _columns(engine, "users")
        finally:
            await engine.dispose()

    async def test_existing_rows_filled(self, scratch_database: str, engine: AsyncEngine) -> None:
        """Завершённым задачам — момент последнего изменения, пользователю — сроки по умолчанию."""
        try:
            user_id, task_ids = await _seed(engine, ["done", "failed", "new"])
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                finished = await connection.execute(
                    sa.text("SELECT id, finished_at = updated_at FROM tasks WHERE id = ANY(:ids)"),
                    {"ids": task_ids},
                )
                user = await connection.execute(
                    sa.text(
                        "SELECT archive_after_days, cleanup_repos_after_days FROM users "
                        "WHERE id = :id",
                    ),
                    {"id": user_id},
                )
                assert {row[0]: row[1] for row in finished} == {
                    task_ids[0]: True,
                    task_ids[1]: True,
                    task_ids[2]: None,
                }
                assert user.one() == (14, 30)
        finally:
            await engine.dispose()

    @pytest.mark.parametrize("final_status", ["done", "failed"])
    async def test_downgrade_restores_final_status(
        self,
        scratch_database: str,
        engine: AsyncEngine,
        final_status: str,
    ) -> None:
        try:
            run_alembic(scratch_database, "upgrade", _REVISION)
            _, (task_id,) = await _seed(engine, [final_status])
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "UPDATE tasks SET status = 'archived', archived_from_status = :status "
                        "WHERE id = :id",
                    ),
                    {"id": task_id, "status": final_status},
                )
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            async with engine.connect() as connection:
                status = await connection.scalar(
                    sa.text("SELECT status::text FROM tasks WHERE id = :id"),
                    {"id": task_id},
                )
            assert status == final_status
        finally:
            await engine.dispose()

    @pytest.mark.parametrize("days", [-1, 3651, None], ids=["negative", "too_long", "null"])
    async def test_days_out_of_range_rejected(
        self,
        scratch_database: str,
        engine: AsyncEngine,
        days: int,
    ) -> None:
        try:
            run_alembic(scratch_database, "upgrade", _REVISION)
            user_id, _ = await _seed(engine, [])
            for column in _USER_COLUMNS:
                with pytest.raises(sa.exc.IntegrityError):
                    async with engine.begin() as connection:
                        await connection.execute(
                            sa.text(f"UPDATE users SET {column} = :days WHERE id = :id"),
                            {"days": days, "id": user_id},
                        )
        finally:
            await engine.dispose()

    @pytest.mark.parametrize("days", [0, 3650])
    async def test_days_boundaries_accepted(
        self,
        scratch_database: str,
        engine: AsyncEngine,
        days: int,
    ) -> None:
        """0 — срок выключен, задачи хранятся бессрочно."""
        try:
            run_alembic(scratch_database, "upgrade", _REVISION)
            user_id, _ = await _seed(engine, [])
            async with engine.begin() as connection:
                for column in _USER_COLUMNS:
                    await connection.execute(
                        sa.text(f"UPDATE users SET {column} = :days WHERE id = :id"),
                        {"days": days, "id": user_id},
                    )
        finally:
            await engine.dispose()
