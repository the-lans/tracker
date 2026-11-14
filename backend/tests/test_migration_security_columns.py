"""
Миграция `e7b2d9c4a613`: `git_credentials.ssh_known_hosts` и
`users.session_version` (разделы 3.1, 19.1, 19.3). Существующие пользователи
получают версию 0 — выданные до обновления токены продолжают действовать.
Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "c1d4e7a2b958"
_REVISION = "e7b2d9c4a613"
_USER_INSERT = "INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)"
_COLUMNS_QUERY = (
    "SELECT count(*) FROM information_schema.columns WHERE "
    "(table_name = 'git_credentials' AND column_name = 'ssh_known_hosts') OR "
    "(table_name = 'users' AND column_name = 'session_version')"
)


class TestSecurityColumnsMigration:
    async def test_existing_users_keep_sessions(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        user_id = uuid.uuid4()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(_USER_INSERT),
                    {"id": user_id, "email": "a@example.com"},
                )
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                version = (
                    await connection.execute(
                        sa.text("SELECT session_version FROM users WHERE id = :id"),
                        {"id": user_id},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()
        assert version == 0

    async def test_downgrade_and_repeat(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            async with engine.connect() as connection:
                dropped = (await connection.execute(sa.text(_COLUMNS_QUERY))).scalar_one()
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                restored = (await connection.execute(sa.text(_COLUMNS_QUERY))).scalar_one()
        finally:
            await engine.dispose()
        assert (dropped, restored) == (0, 2)
