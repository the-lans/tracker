"""Переход на cookie отзывает токены; откат не возвращает их."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.migration_support import run_alembic


class TestBrowserSessionMigration:
    async def test_revoke_survives_downgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", "e4ac0721df52")
        engine = create_async_engine(scratch_database)
        user_id = uuid.uuid4()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "INSERT INTO users (id, email, role, is_active, session_version) "
                        "VALUES (:id, 'migration@example.com', 'user', true, 4)"
                    ),
                    {"id": user_id},
                )
            run_alembic(scratch_database, "upgrade", "f8c1a6d2b940")
            async with engine.connect() as connection:
                assert (
                    await connection.execute(sa.text("SELECT session_version FROM users"))
                ).scalar_one() == 5
            run_alembic(scratch_database, "downgrade", "e4ac0721df52")
            async with engine.connect() as connection:
                assert (
                    await connection.execute(sa.text("SELECT session_version FROM users"))
                ).scalar_one() == 5
        finally:
            await engine.dispose()
