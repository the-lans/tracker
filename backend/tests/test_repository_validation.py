"""
Поля репозитория, попадающие в пути и в командную строку git (раздел 3.1 ТЗ):
значение с `-` в начале git принял бы за опцию, `..` вывело бы клон за пределы
каталога задачи.
"""

from __future__ import annotations

import subprocess
import uuid
from typing import TYPE_CHECKING

import pytest

from db.models.enums import RepositoryRole
from db.models.repositories import Repository
from db.models.tasks import TaskRepository
from services.crypto import encrypt
from services.errors import ExternalServiceError, ValidationError
from services.git_ops import clone_task_repository
from services.repository_validation import (
    validate_branch_name,
    validate_git_url,
    validate_repository_name,
)

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient


class TestRepositoryName:
    @pytest.mark.parametrize("name", ["backend", "web-app", "lib_1.2"])
    def test_accepted(self, name: str) -> None:
        assert validate_repository_name(name) == name

    @pytest.mark.parametrize("name", ["", ".", "..", "../RR-1/A", "a/b", "-x", "my repo"])
    def test_rejected(self, name: str) -> None:
        with pytest.raises(ValidationError):
            validate_repository_name(name)


class TestGitUrl:
    @pytest.mark.parametrize(
        "git_url",
        [
            "git@gitlab.example.com:group/project.git",
            "ssh://git@gitlab.example.com:2222/group/project.git",
            "https://gitlab.example.com/group/project.git",
        ],
    )
    def test_accepted(self, git_url: str) -> None:
        assert validate_git_url(git_url) == git_url

    @pytest.mark.parametrize(
        "git_url",
        [
            "--upload-pack=touch /tmp/x",
            "-u x",
            "ext::sh -c touch% /tmp/x",
            "file:///data/repos/RR-1/backend",
            "/data/repos/RR-1/backend",
            "git@host:path with space",
        ],
    )
    def test_rejected(self, git_url: str) -> None:
        with pytest.raises(ValidationError):
            validate_git_url(git_url)


class TestBranchName:
    @pytest.mark.parametrize("branch", ["main", "release/1.2", "feature/RR-1"])
    def test_accepted(self, branch: str) -> None:
        assert validate_branch_name(branch) == branch

    @pytest.mark.parametrize(
        "branch",
        ["", "--upload-pack=x", "-b", "a..b", "a b", "/main", "main/", "a//b", "x.lock"],
    )
    def test_rejected(self, branch: str) -> None:
        with pytest.raises(ValidationError):
            validate_branch_name(branch)


class TestCloneTreatsUrlAsArgument:
    async def test_option_in_url_not_executed(self, tmp_path: Path) -> None:
        """
        Цепочка из ревью: `git_url` с `--upload-pack=` и каталог клона,
        указывающий на существующий репозиторий. После `--` адрес — не опция.
        """
        existing = tmp_path / "repos" / "RR-00001" / "A"
        subprocess.run(["git", "init", "-q", str(existing)], check=True)
        marker = tmp_path / "pwned"
        repository = Repository(
            id=uuid.uuid4(),
            name="../RR-00001/A",
            git_url=f"--upload-pack=touch {marker}; git-upload-pack",
            deploy_key_encrypted=encrypt("key"),
        )
        task_repository = TaskRepository(
            task_id=uuid.uuid4(),
            repository_id=repository.id,
            role=RepositoryRole.READ_WRITE,
            branch_name="feature/RR-00002",
            base_branch="main",
        )
        with pytest.raises(ExternalServiceError):
            await clone_task_repository(
                repository=repository,
                task_repository=task_repository,
                task_code="RR-00002",
                repos_root=tmp_path / "repos",
            )
        assert not marker.exists()


class TestRepositoryApi:
    async def test_create_rejects_option_in_url(self, authed_client: AsyncClient) -> None:
        response = await authed_client.post(
            "/repositories",
            json={"name": "backend", "git_url": "--upload-pack=id", "deploy_key": "k"},
        )
        assert response.status_code == 422

    async def test_create_rejects_path_in_name(self, authed_client: AsyncClient) -> None:
        response = await authed_client.post(
            "/repositories",
            json={
                "name": "../RR-1/backend",
                "git_url": "git@gitlab.example.com:group/backend.git",
                "deploy_key": "k",
            },
        )
        assert response.status_code == 422

    async def test_task_rejects_option_as_base_branch(self, authed_client: AsyncClient) -> None:
        created = await authed_client.post(
            "/repositories",
            json={
                "name": "backend",
                "git_url": "git@gitlab.example.com:group/backend.git",
                "deploy_key": "k",
            },
        )
        response = await authed_client.post(
            "/tasks",
            json={
                "code": "RR-31337",
                "title": "t",
                "description": "d",
                "repositories": [
                    {
                        "repository_id": created.json()["id"],
                        "role": "read_write",
                        "base_branch": "--upload-pack=id",
                    },
                ],
            },
        )
        assert response.status_code == 422

    async def test_rename_rejected_while_task_active(self, authed_client: AsyncClient) -> None:
        created = await authed_client.post(
            "/repositories",
            json={
                "name": "backend",
                "git_url": "git@gitlab.example.com:group/backend.git",
                "deploy_key": "k",
            },
        )
        repository_id = created.json()["id"]
        await authed_client.post(
            "/tasks",
            json={
                "code": "RR-31338",
                "title": "t",
                "description": "d",
                "repositories": [
                    {"repository_id": repository_id, "role": "read_write", "base_branch": "main"},
                ],
            },
        )
        renamed = await authed_client.patch(
            f"/repositories/{repository_id}",
            json={"name": "backend-2"},
        )
        assert renamed.status_code == 409
        same_name = await authed_client.patch(
            f"/repositories/{repository_id}",
            json={"name": "backend", "git_url": "git@gitlab.example.com:group/other.git"},
        )
        assert same_name.status_code == 200
