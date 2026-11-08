"""
Миграция команд и одновременные повторные запросы на независимых соединениях БД.
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.enums import NodeType, ScriptLanguage, TaskStatus
from db.models.pipelines import Node
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services.library_commands import enqueue_command
from tests.factories import make_task, make_user
from tests.migration_support import run_alembic

_REVISION = "d7a41e9b5206"
_PREVIOUS = "c9e2f6a81034"
_MIGRATION = (
    Path(__file__).resolve().parents[2] / f"alembic/versions/{_REVISION}_library_commands.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("commands_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def seed(session: AsyncSession) -> Task:
    user = await make_user(session)
    task = await make_task(session, created_by=user.id, status=TaskStatus.IN_PROGRESS)
    session.add(
        Node(
            created_by=user.id,
            name="Test",
            is_library_item=True,
            slash_name="test",
            node_type=NodeType.SCRIPT,
            script_language=ScriptLanguage.PYTHON,
            script_content="print('ok')",
        )
    )
    await session.commit()
    return task


class TestCommandMigration:
    async def test_upgrade_repeat_downgrade(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS)
        run_alembic(scratch_database, "upgrade", _REVISION)
        engine = create_async_engine(scratch_database)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:

                def repeat(sync: Connection) -> None:
                    with Operations.context(MigrationContext.configure(sync)):
                        load_migration().upgrade()

                await connection.run_sync(repeat)
            run_alembic(scratch_database, "upgrade", "head")
            async with sessions() as session:
                task = await seed(session)
                request = await enqueue_command(
                    session,
                    task=task,
                    requested_by=task.created_by,
                    invocation="/test",
                    client_request_id=uuid.uuid4(),
                )
                request_id = request.id
            run_alembic(scratch_database, "downgrade", _PREVIOUS)
            async with engine.connect() as connection:
                status = await connection.scalar(
                    sa.text("SELECT status FROM task_manual_request_queue WHERE id=:id"),
                    {"id": request_id},
                )
                assert status == "cancelled"
            run_alembic(scratch_database, "upgrade", _REVISION)
        finally:
            await engine.dispose()


class TestConcurrentCommands:
    async def test_retry_creates_one_request(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", "head")
        engine = create_async_engine(scratch_database)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session:
                task = await seed(session)
                task_id, owner_id = task.id, task.created_by
            client_id = uuid.uuid4()

            async def submit() -> uuid.UUID:
                async with sessions() as session:
                    loaded = await session.get(Task, task_id)
                    assert loaded is not None
                    row = await enqueue_command(
                        session,
                        task=loaded,
                        requested_by=owner_id,
                        invocation="/test value",
                        client_request_id=client_id,
                    )
                    return row.id

            first, second = await asyncio.gather(submit(), submit())
            assert first == second
            async with sessions() as session:
                assert (
                    await session.scalar(
                        sa.select(sa.func.count()).select_from(TaskManualRequestQueue)
                    )
                    == 1
                )
        finally:
            await engine.dispose()
