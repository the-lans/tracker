"""
Миграция `b7d3e91a4c52`: настройки бэкапа в S3 и таблица `backup_runs`.
Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "e5b81c4d2f97"
_REVISION = "b7d3e91a4c52"
_SETTINGS_INSERT = (
    "INSERT INTO system_settings (id, default_timeout_seconds, default_max_retries, "
    "default_retry_base_delay_seconds, default_runner_image_python, "
    "default_runner_image_bash) VALUES (1, 60, 1, 5, 'p', 'b') ON CONFLICT (id) DO NOTHING"
)


async def _settings_columns(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'system_settings' AND column_name LIKE 'backup_%'",
            ),
        )
        return set(rows.scalars())


async def _has_runs_table(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        found = await connection.execute(sa.text("SELECT to_regclass('backup_runs')"))
        return found.scalar_one() is not None


class TestBackupS3Migration:
    async def test_defaults_for_existing_row(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(_SETTINGS_INSERT))
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        sa.text(
                            "SELECT backup_enabled, backup_s3_folder, backup_retention_count, "
                            "backup_passphrase_encrypted FROM system_settings",
                        ),
                    )
                ).one()
        finally:
            await engine.dispose()
        assert tuple(row) == (False, "Tracker", 7, None)

    async def test_repeated_upgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert await _settings_columns(engine) == set()
            assert not await _has_runs_table(engine)
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert len(await _settings_columns(engine)) == 9
            assert await _has_runs_table(engine)
        finally:
            await engine.dispose()

    @pytest.mark.parametrize("count", [0, 366])
    async def test_retention_out_of_range(self, scratch_database: str, count: int) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        engine = create_async_engine(scratch_database)
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(_SETTINGS_INSERT))
            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        sa.text("UPDATE system_settings SET backup_retention_count = :count"),
                        {"count": count},
                    )
        finally:
            await engine.dispose()
