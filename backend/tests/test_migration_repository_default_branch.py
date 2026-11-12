"""
Миграция `d2b7f4a9c613`: `repositories.default_branch`. Проверяется на
отдельной временной базе.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "c4e7a2b9d518"
_REVISION = "d2b7f4a9c613"
_COLUMN_QUERY = (
    "SELECT count(*) FROM information_schema.columns "
    "WHERE table_name = 'repositories' AND column_name = 'default_branch'"
)


class TestRepositoryDefaultBranchMigration:
    async def test_existing_repository_gets_master(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "INSERT INTO repositories (id, name, git_url) "
                        "VALUES (:id, 'app', 'https://git.example.com/team/app.git')",
                    ),
                    {"id": uuid.uuid4()},
                )
            run_alembic(scratch_database, "upgrade", _REVISION)
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                branch = (
                    await connection.execute(sa.text("SELECT default_branch FROM repositories"))
                ).scalar_one()
        finally:
            await engine.dispose()
        assert branch == "master"

    async def test_downgrade_drops_column(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            async with engine.connect() as connection:
                count = (await connection.execute(sa.text(_COLUMN_QUERY))).scalar_one()
        finally:
            await engine.dispose()
        assert count == 0
