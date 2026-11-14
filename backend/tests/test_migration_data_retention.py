"""
Миграция `b7d4e2a9c615`: сроки хранения данных (разделы 6.4, 14.3, 17.2).
Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "f3a8c5e1d927"
_REVISION = "b7d4e2a9c615"
_COLUMNS = {
    "tasks": {"session_cleaned_at", "artifacts_cleaned_at"},
    "users": {"artifacts_retention_days"},
    "system_settings": {"app_logs_retention_days"},
}
_USER_INSERT = (
    "INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)"
)
_SETTINGS_INSERT = (
    "INSERT INTO system_settings (id, default_timeout_seconds, default_max_retries, "
    "default_retry_base_delay_seconds, default_runner_image_python, default_runner_image_bash) "
    "VALUES (1, 600, 3, 5, 'python', 'bash') ON CONFLICT (id) DO NOTHING"
)


async def _columns(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = :table"),
            {"table": table},
        )
        return set(rows.scalars())


async def _added_columns(engine: AsyncEngine) -> dict[str, set[str]]:
    return {table: columns & await _columns(engine, table) for table, columns in _COLUMNS.items()}


async def _seed_user(engine: AsyncEngine) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(_USER_INSERT),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    return user_id


@pytest.fixture
async def engine(scratch_database: str) -> AsyncEngine:
    run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
    return create_async_engine(scratch_database)


class TestDataRetentionMigration:
    async def test_repeated_upgrade(self, scratch_database: str, engine: AsyncEngine) -> None:
        try:
            run_alembic(scratch_database, "upgrade", _REVISION)
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            assert await _added_columns(engine) == {table: set() for table in _COLUMNS}
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert await _added_columns(engine) == _COLUMNS
        finally:
            await engine.dispose()

    async def test_existing_rows_get_defaults(
        self,
        scratch_database: str,
        engine: AsyncEngine,
    ) -> None:
        try:
            user_id = await _seed_user(engine)
            async with engine.begin() as connection:
                await connection.execute(sa.text(_SETTINGS_INSERT))
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                artifacts_days = await connection.scalar(
                    sa.text("SELECT artifacts_retention_days FROM users WHERE id = :id"),
                    {"id": user_id},
                )
                app_logs_days = await connection.scalar(
                    sa.text("SELECT app_logs_retention_days FROM system_settings"),
                )
            assert (artifacts_days, app_logs_days) == (90, 30)
        finally:
            await engine.dispose()

    @pytest.mark.parametrize("days", [-1, 3651, None], ids=["negative", "too_long", "null"])
    async def test_days_out_of_range_rejected(
        self,
        scratch_database: str,
        engine: AsyncEngine,
        days: int | None,
    ) -> None:
        try:
            run_alembic(scratch_database, "upgrade", _REVISION)
            user_id = await _seed_user(engine)
            with pytest.raises(sa.exc.IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        sa.text("UPDATE users SET artifacts_retention_days = :days WHERE id = :id"),
                        {"days": days, "id": user_id},
                    )
        finally:
            await engine.dispose()
