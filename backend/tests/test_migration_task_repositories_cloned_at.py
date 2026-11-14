"""
Миграция `c1d4e7a2b958`: `task_repositories.cloned_at`. У задач, которые уже
запускались или общались в чате, привязки считаются склонированными.
Проверяется на отдельной временной базе.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.migration_support import run_alembic

_PREVIOUS_REVISION = "37d3c9b76180"
_REVISION = "c1d4e7a2b958"
_USER_INSERT = "INSERT INTO users (id, email, role, is_active) VALUES (:id, :email, 'user', true)"
_TASK_INSERT = (
    "INSERT INTO tasks (id, code, title, description, status, use_parent_summary, "
    "auto_accept_plan, remote_control_status, remote_control_reconnect_attempts, "
    "auto_start_enabled, created_by, session_id) VALUES (:id, :code, 't', 'd', :status, false, "
    "false, 'unavailable', 0, false, :user_id, :session_id)"
)
_REPOSITORY_INSERT = (
    "INSERT INTO repositories (id, name, git_url) VALUES (:id, 'app', 'git@example.com:app.git')"
)
_BINDING_INSERT = (
    "INSERT INTO task_repositories (id, task_id, repository_id, role, branch_name, base_branch, "
    "merge_status) VALUES (:id, :task_id, :repository_id, 'read_only', 'feature/x', 'main', "
    "'not_pushed')"
)
_COLUMN_QUERY = (
    "SELECT count(*) FROM information_schema.columns "
    "WHERE table_name = 'task_repositories' AND column_name = 'cloned_at'"
)


class TestTaskRepositoriesClonedAtMigration:
    @pytest.mark.parametrize(
        ("status", "session_id", "cloned"),
        [
            ("new", None, False),
            ("ready", None, False),
            ("refining", "sess-chat", True),
            ("in_progress", None, True),
            ("done", None, True),
        ],
    )
    async def test_started_tasks_are_cloned(
        self,
        scratch_database: str,
        status: str,
        session_id: str | None,
        *,
        cloned: bool,
    ) -> None:
        run_alembic(scratch_database, "upgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        user_id, task_id, repository_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    sa.text(_USER_INSERT),
                    {"id": user_id, "email": "a@example.com"},
                )
                await connection.execute(
                    sa.text(_TASK_INSERT),
                    {
                        "id": task_id,
                        "code": "RR-1",
                        "status": status,
                        "user_id": user_id,
                        "session_id": session_id,
                    },
                )
                await connection.execute(sa.text(_REPOSITORY_INSERT), {"id": repository_id})
                await connection.execute(
                    sa.text(_BINDING_INSERT),
                    {"id": uuid.uuid4(), "task_id": task_id, "repository_id": repository_id},
                )
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                cloned_at = (
                    await connection.execute(sa.text("SELECT cloned_at FROM task_repositories"))
                ).scalar_one()
        finally:
            await engine.dispose()
        assert (cloned_at is not None) is cloned

    async def test_downgrade_and_repeat(self, scratch_database: str) -> None:
        run_alembic(scratch_database, "upgrade", _REVISION)
        run_alembic(scratch_database, "downgrade", _PREVIOUS_REVISION)
        engine = create_async_engine(scratch_database)
        try:
            async with engine.connect() as connection:
                dropped = (await connection.execute(sa.text(_COLUMN_QUERY))).scalar_one()
            run_alembic(scratch_database, "upgrade", _REVISION)
            async with engine.connect() as connection:
                restored = (await connection.execute(sa.text(_COLUMN_QUERY))).scalar_one()
        finally:
            await engine.dispose()
        assert (dropped, restored) == (0, 1)
