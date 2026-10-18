"""`api/repositories.py` — CRUD + запрет удаления привязанного к активной
задаче репозитория (правило 9 CLAUDE.md, раздел 3.2 ТЗ)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import RepositoryRole, TaskStatus
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.users import User

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_create_repository_encrypts_deploy_key(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    response = await authed_client.post(
        "/repositories",
        json={
            "name": "tracker",
            "git_url": "git@example.com:org/tracker.git",
            "deploy_key": "SECRET-KEY",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "deploy_key" not in body
    repository = await db_session.get(Repository, uuid.UUID(body["id"]))
    assert repository is not None
    assert repository.deploy_key_encrypted != "SECRET-KEY"


async def test_delete_repository_bound_to_active_task_is_rejected(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    repository = Repository(
        id=uuid.uuid4(),
        name="repo",
        git_url="git@example.com:org/repo.git",
        deploy_key_encrypted="enc",
    )
    db_session.add(repository)
    task = Task(
        id=uuid.uuid4(),
        code=f"RR-{uuid.uuid4().hex[:8]}",
        title="t",
        description="",
        status=TaskStatus.IN_PROGRESS,
        created_by=current_user.id,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        TaskRepository(
            task_id=task.id,
            repository_id=repository.id,
            role=RepositoryRole.READ_WRITE,
            branch_name="feature/x",
            base_branch="main",
        ),
    )
    await db_session.flush()

    response = await authed_client.delete(f"/repositories/{repository.id}")

    assert response.status_code == 409


async def test_delete_repository_bound_to_terminal_task_still_blocked_by_history(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    """Guard (раздел 3.2: "привязанного к активной задаче") пропускает
    репозиторий терминальной задачи, но физическое удаление всё равно
    невозможно — `task_repositories` хранит постоянную историческую запись
    (FK без каскада), поэтому эндпоинт возвращает 409, а не падает с
    сырой ошибкой БД (см. комментарий в `api/repositories.py::delete_repository`)."""
    repository = Repository(
        id=uuid.uuid4(),
        name="repo-done",
        git_url="git@example.com:org/repo-done.git",
        deploy_key_encrypted="enc",
    )
    db_session.add(repository)
    task = Task(
        id=uuid.uuid4(),
        code=f"RR-{uuid.uuid4().hex[:8]}",
        title="t",
        description="",
        status=TaskStatus.DONE,
        created_by=current_user.id,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        TaskRepository(
            task_id=task.id,
            repository_id=repository.id,
            role=RepositoryRole.READ_WRITE,
            branch_name="feature/x",
            base_branch="main",
        ),
    )
    await db_session.flush()

    response = await authed_client.delete(f"/repositories/{repository.id}")

    assert response.status_code == 409
