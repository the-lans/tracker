"""`api/repositories.py` — CRUD + запрет удаления привязанного к активной
задаче репозитория (правило 9 CLAUDE.md, раздел 3.2 ТЗ)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import RepositoryRole, TaskStatus
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from services import git_ops

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_delete_repository_bound_to_active_task_is_rejected(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    current_user: User,
) -> None:
    repository = Repository(
        id=uuid.uuid4(),
        name="repo",
        git_url="git@example.com:org/repo.git",
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


PUBLIC_URL = "https://git.example.com/team/app.git"
DEFAULT_BRANCH_PATH = "/repositories/default-branch"


class TestRepositoryDefaultBranch:
    @pytest.mark.parametrize(
        ("body", "expected"),
        [({}, "master"), ({"default_branch": "develop"}, "develop")],
    )
    async def test_create(
        self,
        authed_client: AsyncClient,
        body: dict[str, str],
        expected: str,
    ) -> None:
        response = await authed_client.post(
            "/repositories", json={"name": "app", "git_url": PUBLIC_URL, **body},
        )

        assert response.status_code == 201, response.text
        assert response.json()["default_branch"] == expected

    @pytest.mark.parametrize("branch", ["-x", "a..b", ""])
    async def test_invalid_rejected(self, authed_client: AsyncClient, branch: str) -> None:
        response = await authed_client.post(
            "/repositories",
            json={"name": "app", "git_url": PUBLIC_URL, "default_branch": branch},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("body", "expected"),
        [({"default_branch": "trunk"}, "trunk"), ({}, "master")],
    )
    async def test_update(
        self,
        authed_client: AsyncClient,
        body: dict[str, str],
        expected: str,
    ) -> None:
        created = await authed_client.post(
            "/repositories", json={"name": "app", "git_url": PUBLIC_URL},
        )

        response = await authed_client.patch(f"/repositories/{created.json()['id']}", json=body)

        assert response.status_code == 200, response.text
        assert response.json()["default_branch"] == expected


class TestRemoteDefaultBranch:
    async def test_reads_head_of_server(
        self,
        authed_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        run = AsyncMock(return_value=(0, "ref: refs/heads/trunk\tHEAD\nabc\tHEAD\n", ""))
        monkeypatch.setattr(git_ops, "_run_git", run)

        response = await authed_client.post(DEFAULT_BRANCH_PATH, json={"git_url": PUBLIC_URL})

        assert response.status_code == 200
        assert response.json() == {"default_branch": "trunk"}
        assert run.call_args.args == ("ls-remote", "--symref", PUBLIC_URL, "HEAD")

    @pytest.mark.parametrize(
        "git_url",
        ["git@git.example.com:team/app.git", "--upload-pack=touch /tmp/x"],
    )
    async def test_rejected_before_git(
        self,
        authed_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        git_url: str,
    ) -> None:
        run = AsyncMock()
        monkeypatch.setattr(git_ops, "_run_git", run)

        response = await authed_client.post(DEFAULT_BRANCH_PATH, json={"git_url": git_url})

        assert response.status_code == 422
        run.assert_not_called()

    async def test_server_refusal(
        self,
        authed_client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(git_ops, "_run_git", AsyncMock(return_value=(128, "", "denied")))

        response = await authed_client.post(DEFAULT_BRANCH_PATH, json={"git_url": PUBLIC_URL})

        assert response.status_code == 422
        assert "denied" not in response.text
