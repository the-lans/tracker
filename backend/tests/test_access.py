"""`services/access.py` — владение записями (раздел 19.2 ТЗ, решение №16 плана)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeType, TaskStatus, UserRole
from db.models.pipelines import Node, Pipeline
from db.models.repositories import Template
from db.models.tasks import Task
from db.models.users import User
from db.session import async_session_factory
from services.access import (
    authorize_task_stream,
    get_node_for_user,
    get_pipeline_for_user,
    get_task_for_user,
    get_template_for_user,
    owner_filter,
)
from services.errors import NotFoundError, UnauthorizedError
from tests.factories import make_user

Getter = Callable[..., Awaitable[Any]]


def _make_record(kind: str, owner_id: uuid.UUID) -> Task | Pipeline | Node | Template:
    if kind == "task":
        return Task(
            code=f"RR-{uuid.uuid4().hex[:5]}",
            title="t",
            description="d",
            created_by=owner_id,
            status=TaskStatus.NEW,
        )
    if kind == "pipeline":
        return Pipeline(name="p", is_archived=False, created_by=owner_id)
    if kind == "node":
        return Node(
            name="n",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            is_library_item=True,
            created_by=owner_id,
        )
    return Template(name="tpl", files={}, created_by=owner_id)


_GETTERS: dict[str, Getter] = {
    "task": get_task_for_user,
    "pipeline": get_pipeline_for_user,
    "node": get_node_for_user,
    "template": get_template_for_user,
}


@pytest.mark.parametrize("kind", list(_GETTERS))
class TestGetForUser:
    async def test_owner_gets_record(self, db_session: AsyncSession, kind: str) -> None:
        owner = await make_user(db_session)
        record = _make_record(kind, owner.id)
        db_session.add(record)
        await db_session.flush()

        assert await _GETTERS[kind](db_session, record.id, user=owner) is record

    async def test_foreign_record_looks_missing(self, db_session: AsyncSession, kind: str) -> None:
        owner = await make_user(db_session)
        stranger = await make_user(db_session)
        record = _make_record(kind, owner.id)
        db_session.add(record)
        await db_session.flush()

        with pytest.raises(NotFoundError):
            await _GETTERS[kind](db_session, record.id, user=stranger)

    async def test_admin_gets_foreign_record(self, db_session: AsyncSession, kind: str) -> None:
        owner = await make_user(db_session)
        admin = await make_user(db_session, role=UserRole.ADMIN)
        record = _make_record(kind, owner.id)
        db_session.add(record)
        await db_session.flush()

        assert await _GETTERS[kind](db_session, record.id, user=admin) is record

    async def test_missing_record(self, db_session: AsyncSession, kind: str) -> None:
        user = await make_user(db_session)

        with pytest.raises(NotFoundError):
            await _GETTERS[kind](db_session, uuid.uuid4(), user=user)


class TestOwnerFilter:
    @pytest.mark.parametrize(
        ("role", "sees_foreign"),
        [(UserRole.USER, False), (UserRole.ADMIN, True)],
    )
    async def test_selects(
        self,
        db_session: AsyncSession,
        role: UserRole,
        sees_foreign: bool,
    ) -> None:
        viewer = await make_user(db_session, role=role)
        other = await make_user(db_session)
        own = Pipeline(name="own", is_archived=False, created_by=viewer.id)
        foreign = Pipeline(name="foreign", is_archived=False, created_by=other.id)
        db_session.add_all([own, foreign])
        await db_session.flush()

        stmt = sa.select(Pipeline.id).where(
            Pipeline.id.in_([own.id, foreign.id]),
            owner_filter(Pipeline.created_by, viewer),
        )
        found = set((await db_session.execute(stmt)).scalars().all())

        assert found == ({own.id, foreign.id} if sees_foreign else {own.id})


class TestAuthorizeTaskStream:
    """
    Данные коммитятся через `async_session_factory` и удаляются вручную —
    так же, как в `test_ws.py`: канал задачи читает БД своим соединением.
    """

    async def _commit_user(self, *, role: UserRole, is_active: bool = True) -> User:
        user = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4()}@example.com",
            role=role,
            is_active=is_active,
        )
        async with async_session_factory() as session:
            session.add(user)
            await session.commit()
        return user

    async def _cleanup(self, *, task_id: uuid.UUID, user_ids: list[uuid.UUID]) -> None:
        async with async_session_factory() as session:
            await session.execute(sa.delete(Task).where(Task.id == task_id))
            await session.execute(sa.delete(User).where(User.id.in_(user_ids)))
            await session.commit()

    @pytest.mark.parametrize(
        ("viewer_role", "viewer_is_owner", "viewer_active", "expected"),
        [
            (UserRole.USER, True, True, None),
            (UserRole.USER, False, True, NotFoundError),
            (UserRole.ADMIN, False, True, None),
            (UserRole.USER, True, False, UnauthorizedError),
        ],
        ids=["owner", "stranger", "admin", "blocked_owner"],
    )
    async def test_access(
        self,
        run_migrations: None,
        viewer_role: UserRole,
        viewer_is_owner: bool,
        viewer_active: bool,
        expected: type[Exception] | None,
    ) -> None:
        owner = await self._commit_user(role=UserRole.USER, is_active=viewer_active)
        viewer = owner if viewer_is_owner else await self._commit_user(role=viewer_role)
        task = Task(
            code=f"RR-{uuid.uuid4().hex[:6]}",
            title="t",
            description="d",
            created_by=owner.id,
            status=TaskStatus.NEW,
        )
        async with async_session_factory() as session:
            session.add(task)
            await session.commit()

        try:
            async with async_session_factory() as session:
                if expected is None:
                    await authorize_task_stream(session, user_id=viewer.id, task_id=task.id)
                else:
                    with pytest.raises(expected):
                        await authorize_task_stream(session, user_id=viewer.id, task_id=task.id)
        finally:
            await self._cleanup(task_id=task.id, user_ids=[owner.id, viewer.id])
