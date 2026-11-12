"""
Миграция `c4e7a2b9d518`: таблица `events`, ссылка ноды на промт библиотеки,
индекс `app_logs(created_at)`. Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "b7d3e91a4c52"
_REVISION = "c4e7a2b9d518"
_USER_INSERT = (
    "INSERT INTO users (id, email, role, is_active) VALUES (:id, 'qa@example.com', 'user', true)"
)


async def _schema_objects(engine: AsyncEngine) -> tuple[bool, set[str], bool]:
    async with engine.connect() as connection:
        events = await connection.execute(sa.text("SELECT to_regclass('events')"))
        columns = await connection.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'nodes' AND column_name LIKE 'library_%'",
            ),
        )
        index = await connection.execute(sa.text("SELECT to_regclass('ix_app_logs_created_at')"))
        return (
            events.scalar_one() is not None,
            set(columns.scalars()),
            index.scalar_one() is not None,
        )


class TestEventsLibraryLinksMigration:
    async def test_repeated_upgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            assert await _schema_objects(engine) == (False, set(), False)
            run_alembic(scratch_database, "upgrade", _REVISION)
            assert await _schema_objects(engine) == (
                True,
                {"library_node_id", "library_arguments"},
                True,
            )
        finally:
            await engine.dispose()

    @pytest.mark.parametrize(
        ("audience", "with_user", "valid"),
        [
            ("user", True, True),
            ("admins", False, True),
            ("user", False, False),
            ("admins", True, False),
        ],
        ids=["user-адресат", "админам", "user-без-адресата", "админам-с-адресатом"],
    )
    async def test_audience_matches_user(
        self,
        scratch_database: str,
        audience: str,
        with_user: bool,
        valid: bool,
    ) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        engine = create_async_engine(scratch_database)
        user_id = uuid.uuid4()
        insert = sa.text(
            "INSERT INTO events (id, audience, user_id, category, event_type, title, body) "
            "VALUES (:id, CAST(:audience AS event_audience), :user_id, 'task', 'done', 't', 'b')",
        )
        params = {
            "id": uuid.uuid4(),
            "audience": audience,
            "user_id": user_id if with_user else None,
        }
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(_USER_INSERT), {"id": user_id})
            if valid:
                async with engine.begin() as connection:
                    await connection.execute(insert, params)
            else:
                with pytest.raises(IntegrityError):
                    async with engine.begin() as connection:
                        await connection.execute(insert, params)
        finally:
            await engine.dispose()
