"""Старая привязка и данные последнего запуска сохраняются при удалении дублей."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.enums import LibraryPromptRunStatus, NodeType
from db.models.pipelines import Node
from db.models.prompts import TaskLibraryPrompt
from db.models.tasks import Task
from db.models.users import User
from tests.migration_support import run_alembic


class TestTaskLibraryPromptMigration:
    async def test_keeps_position_and_last_run(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", "b4d8e2f6a931")
        engine = create_async_engine(scratch_database)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            added_at = datetime.now(UTC)
            last_run_at = added_at + timedelta(minutes=10)
            async with sessions.begin() as session:
                user = User(email="prompts@example.com")
                session.add(user)
                await session.flush()
                task = Task(
                    code="RR-1", title="Task", description="Description", created_by=user.id
                )
                session.add(task)
                await session.flush()
                node_id = uuid.uuid4()
                # Схема этой ревизии предшествует новым nullable-полям Node.
                await session.execute(
                    sa.insert(Node).values(
                        id=node_id,
                        name="Prompt",
                        node_type=NodeType.PLAIN_PROMPT,
                        prompt_template="Review",
                        is_library_item=True,
                        created_by=user.id,
                    )
                )
                scope = {"task_id": task.id, "node_id": node_id, "added_by": user.id}
                first = TaskLibraryPrompt(**scope, added_at=added_at)
                duplicate = TaskLibraryPrompt(
                    **scope,
                    added_at=added_at + timedelta(minutes=1),
                    last_run_at=last_run_at,
                    last_run_status=LibraryPromptRunStatus.SUCCESS,
                )
                session.add_all([first, duplicate])

            run_alembic(scratch_database, "upgrade", "d1706a5e4fc2")
            async with sessions() as session:
                survivor = (await session.scalars(sa.select(TaskLibraryPrompt))).one()
                assert (survivor.id, survivor.added_at) == (first.id, added_at)
                assert (survivor.last_run_at, survivor.last_run_status) == (
                    last_run_at,
                    LibraryPromptRunStatus.SUCCESS,
                )
            with pytest.raises(IntegrityError):
                async with sessions.begin() as session:
                    session.add(TaskLibraryPrompt(**scope))
        finally:
            await engine.dispose()
