"""
Репозитории задачи после её создания (раздел 3.2 ТЗ): добавление в любом
незавершённом статусе, удаление только несклонированной привязки, пока
сессией задачи никто не владеет.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import RepositoryRole, TaskStatus
from db.models.tasks import Task, TaskRepository
from services.task_repositories import RepositoryAttachment, build_task_repository
from tests.factories import make_repository, make_task

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.repositories import Repository
    from db.models.users import User

pytestmark = pytest.mark.usefixtures("redis_container")


async def _attach(
    db_session: AsyncSession,
    *,
    task: Task,
    repository: Repository,
    cloned: bool = False,
) -> TaskRepository:
    task_repository = build_task_repository(
        task=task,
        attached=RepositoryAttachment(repository_id=repository.id, role=RepositoryRole.READ_ONLY),
        repository=repository,
    )
    task_repository.cloned_at = datetime.now(UTC) if cloned else None
    db_session.add(task_repository)
    await db_session.flush()
    return task_repository


def _body(repository: Repository, **fields: str) -> dict[str, list[dict[str, str]]]:
    return {"repositories": [{"repository_id": str(repository.id), "role": "read_only", **fields}]}


class TestAddRepositories:
    @pytest.mark.parametrize(
        "status",
        [
            TaskStatus.NEW,
            TaskStatus.REFINING,
            TaskStatus.IN_PROGRESS,
            TaskStatus.PAUSED,
            TaskStatus.AWAITING_INPUT,
            TaskStatus.FAILED,
        ],
    )
    async def test_added_in_unfinished_status(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        status: TaskStatus,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id, status=status)
        repository = await make_repository(db_session, name="frontend", default_branch="develop")

        response = await authed_client.post(
            f"/tasks/{task.id}/repositories", json=_body(repository)
        )

        assert response.status_code == 201, response.text
        [added] = response.json()
        assert added["repository_id"] == str(repository.id)
        assert added["role"] == "read_only"
        assert added["branch_name"] == f"feature/{task.code}"
        assert added["base_branch"] == "develop"
        assert added["cloned_at"] is None

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.ARCHIVED])
    async def test_finished_task_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        status: TaskStatus,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id, status=status)
        repository = await make_repository(db_session)

        response = await authed_client.post(
            f"/tasks/{task.id}/repositories", json=_body(repository)
        )

        assert response.status_code == 409

    async def test_already_attached_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id)
        repository = await make_repository(db_session)
        await _attach(db_session, task=task, repository=repository)

        response = await authed_client.post(
            f"/tasks/{task.id}/repositories", json=_body(repository)
        )

        assert response.status_code == 409

    @pytest.mark.parametrize(
        ("body", "status_code"),
        [
            ({"repositories": []}, 422),
            ({"repositories": [{"repository_id": str(uuid.uuid4()), "role": "read_only"}]}, 404),
        ],
    )
    async def test_invalid_body(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        body: dict[str, object],
        status_code: int,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id)

        response = await authed_client.post(f"/tasks/{task.id}/repositories", json=body)

        assert response.status_code == status_code

    async def test_invalid_branch_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id)
        repository = await make_repository(db_session)

        response = await authed_client.post(
            f"/tasks/{task.id}/repositories",
            json=_body(repository, base_branch="-x"),
        )

        assert response.status_code == 422

    async def test_foreign_task_not_found(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        task = await make_task(db_session)
        repository = await make_repository(db_session)

        response = await authed_client.post(
            f"/tasks/{task.id}/repositories", json=_body(repository)
        )

        assert response.status_code == 404


class TestRemoveRepository:
    async def _count(self, db_session: AsyncSession, task: Task) -> int:
        stmt = sa.select(sa.func.count()).where(TaskRepository.task_id == task.id)
        return int(await db_session.scalar(stmt) or 0)

    @pytest.mark.parametrize("status", [TaskStatus.NEW, TaskStatus.READY, TaskStatus.FAILED])
    async def test_not_cloned_removed(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        status: TaskStatus,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id, status=status)
        attached = await _attach(
            db_session, task=task, repository=await make_repository(db_session)
        )

        response = await authed_client.delete(f"/tasks/{task.id}/repositories/{attached.id}")

        assert response.status_code == 204
        assert await self._count(db_session, task) == 0

    @pytest.mark.parametrize(
        ("status", "cloned", "chat_active"),
        [
            (TaskStatus.NEW, True, False),
            (TaskStatus.IN_PROGRESS, False, False),
            (TaskStatus.PAUSED, False, False),
            (TaskStatus.REFINING, False, True),
        ],
    )
    async def test_rejected_while_cloned_or_owned(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        status: TaskStatus,
        *,
        cloned: bool,
        chat_active: bool,
    ) -> None:
        task = await make_task(
            db_session,
            created_by=current_user.id,
            status=status,
            chat_active=chat_active,
        )
        repository = await make_repository(db_session)
        attached = await _attach(db_session, task=task, repository=repository, cloned=cloned)

        response = await authed_client.delete(f"/tasks/{task.id}/repositories/{attached.id}")

        assert response.status_code == 409
        assert await self._count(db_session, task) == 1

    async def test_other_task_binding_not_found(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id)
        other = await make_task(db_session, created_by=current_user.id)
        attached = await _attach(
            db_session, task=other, repository=await make_repository(db_session)
        )

        response = await authed_client.delete(f"/tasks/{task.id}/repositories/{attached.id}")

        assert response.status_code == 404
