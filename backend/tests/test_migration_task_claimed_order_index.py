"""
Миграция `b4d8e2f6a931`: `tasks.claimed_order_index` (раздел 13.2). Проверяется на
отдельной временной базе: столбец добавляется, повторный запуск безвреден, откат его убирает.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "a7e2c9d4b185"
_REVISION = "b4d8e2f6a931"
_COLUMN_QUERY = (
    "SELECT is_nullable FROM information_schema.columns "
    "WHERE table_name = 'tasks' AND column_name = 'claimed_order_index'"
)


async def _column_nullable(engine: AsyncEngine) -> str | None:
    async with engine.connect() as connection:
        return (await connection.execute(sa.text(_COLUMN_QUERY))).scalar_one_or_none()


class TestClaimedOrderIndexMigration:
    async def test_adds_nullable_column(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert await _column_nullable(engine) is None
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert await _column_nullable(engine) == "YES"
        finally:
            await engine.dispose()

    async def test_repeated_upgrade_and_downgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert await _column_nullable(engine) is None
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert await _column_nullable(engine) == "YES"
        finally:
            await engine.dispose()
