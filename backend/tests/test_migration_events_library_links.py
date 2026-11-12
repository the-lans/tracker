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


_PIPELINE_INSERT = (
    "INSERT INTO pipelines (id, name, is_archived, created_by, created_at, updated_at) "
    "VALUES (:id, 'Пайплайн', false, :user_id, now(), now())"
)
_NODE_INSERT = (
    "INSERT INTO nodes (id, pipeline_id, order_index, name, node_type, prompt_template, "
    "guide_url, timeout_seconds, max_retries, retry_base_delay_seconds, is_skipped, "
    "is_library_item, is_archived, created_by, library_node_id) "
    "VALUES (:id, :pipeline_id, :order_index, :name, 'plain_prompt', :prompt, :guide, "
    "60, 0, 1, false, :is_library_item, false, :user_id, :library_node_id)"
)


class TestLibraryLinksDowngrade:
    """Прежняя версия получает ноды со своим текстом, без {{node.guide_url}}."""

    async def test_materializes_library_content(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        engine = create_async_engine(scratch_database)
        user_id, pipeline_id, library_id, linked_id = (uuid.uuid4() for _ in range(4))
        library = {
            "id": library_id,
            "pipeline_id": None,
            "order_index": None,
            "name": "Ревью",
            "prompt": "Сверь с {{ node.guide_url }} и {{task.title}}",
            "guide": "https://wiki.example.com/review",
            "is_library_item": True,
            "user_id": user_id,
            "library_node_id": None,
        }
        linked = library | {
            "id": linked_id,
            "pipeline_id": pipeline_id,
            "order_index": 0,
            "name": "Шаг",
            "prompt": None,
            "guide": None,
            "is_library_item": False,
            "library_node_id": library_id,
        }
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(_USER_INSERT), {"id": user_id})
                await connection.execute(
                    sa.text(_PIPELINE_INSERT),
                    {"id": pipeline_id, "user_id": user_id},
                )
                await connection.execute(sa.text(_NODE_INSERT), library)
                await connection.execute(sa.text(_NODE_INSERT), linked)
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            async with engine.connect() as connection:
                rows = await connection.execute(
                    sa.text("SELECT id, prompt_template, guide_url FROM nodes"),
                )
                nodes = {row.id: (row.prompt_template, row.guide_url) for row in rows}
        finally:
            await engine.dispose()
        expected = (
            "Сверь с https://wiki.example.com/review и {{task.title}}",
            "https://wiki.example.com/review",
        )
        assert nodes == {library_id: expected, linked_id: expected}
