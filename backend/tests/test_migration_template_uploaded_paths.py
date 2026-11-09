"""
Миграция `c7e4b19a3d60`: `templates.uploaded_file_paths`. Проверяется на
отдельной временной базе.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "a3f9d2c71e58"
_REVISION = "c7e4b19a3d60"
_COLUMN_QUERY = (
    "SELECT count(*) FROM information_schema.columns "
    "WHERE table_name = 'templates' AND column_name = 'uploaded_file_paths'"
)


class TestTemplateUploadedPathsMigration:
    async def test_existing_template_gets_empty_list(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        user_id = uuid.uuid4()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(
                        "INSERT INTO users (id, email, role, is_active) "
                        "VALUES (:id, :email, 'user', true)",
                    ),
                    {"id": user_id, "email": f"{user_id}@example.com"},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO templates (id, name, files, created_by) "
                        "VALUES (:id, 't', '{\"CLAUDE.md\": \"x\"}', :user_id)",
                    ),
                    {"id": uuid.uuid4(), "user_id": user_id},
                )
            run_alembic(scratch_database, "upgrade", _REVISION)
            run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                paths = (
                    await connection.execute(sa.text("SELECT uploaded_file_paths FROM templates"))
                ).scalar_one()
        finally:
            await engine.dispose()
        assert paths == []

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
