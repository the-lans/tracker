"""Тесты `services/git_ops.py` (этап 4 плана реализации).

Раздел 21.1 ТЗ требует тестировать клонирование "тестового репозитория
(локальный bare-repo в тесте, не реальный GitLab) по SSH". Реальный SSH
демон в тестовом окружении не поднимается — вместо этого используется
локальный bare-репозиторий по файловому transport'у git (`git clone
<путь>`), который упражняет ровно ту же логику `git_ops.py` (клонирование,
создание ветки, push, fetch, rebase, обработка конфликта), не завязываясь
на транспорт. `GIT_SSH_COMMAND`, который `git_ops.py` всегда выставляет,
для файлового transport'а просто не используется git'ом — безвреден.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest

from db.models.enums import RepositoryRole
from db.models.repositories import Repository
from db.models.tasks import TaskRepository
from services.crypto import encrypt
from services.errors import ExternalServiceError
from services.git_ops import (
    RebaseConflictError,
    clone_task_repository,
    push_task_repository,
    rebase_onto_base_branch,
)

_GIT_AUTHOR_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def _init_bare_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _run("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)

    seed_dir = tmp_path / "seed"
    _run("git", "clone", str(origin), str(seed_dir), cwd=tmp_path)
    (seed_dir / "README.md").write_text("исходный файл\n")
    _run("git", "add", "README.md", cwd=seed_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "начальный коммит", cwd=seed_dir)
    _run("git", "branch", "-M", "main", cwd=seed_dir)
    _run("git", "push", "origin", "main", cwd=seed_dir)
    return origin


_UNUSED_DEPLOY_KEY_PLACEHOLDER = "не используется файловым transport'ом, но должен расшифровываться"


def _make_repository(*, git_url: str) -> Repository:
    return Repository(
        id=uuid.uuid4(),
        name="demo-repo",
        git_url=git_url,
        deploy_key_encrypted=encrypt(_UNUSED_DEPLOY_KEY_PLACEHOLDER),
    )


def _make_task_repository(
    *,
    role: RepositoryRole,
    branch_name: str = "feature/RR-00001",
) -> TaskRepository:
    return TaskRepository(
        id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        role=role,
        branch_name=branch_name,
        base_branch="main",
    )


async def test_clone_task_repository_creates_working_branch(tmp_path: Path) -> None:
    origin = _init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)

    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )

    assert (target_dir / "README.md").exists()
    current_branch = _run("git", "branch", "--show-current", cwd=target_dir).strip()
    assert current_branch == "feature/RR-00001"


async def test_push_task_repository_pushes_when_read_write(tmp_path: Path) -> None:
    origin = _init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    (target_dir / "new_file.txt").write_text("новый файл\n")
    _run("git", "add", "new_file.txt", cwd=target_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "добавить файл", cwd=target_dir)

    await push_task_repository(
        repository=repository,
        task_repository=task_repository,
        repo_dir=target_dir,
    )

    remote_branches = _run("git", "branch", "-r", cwd=target_dir)
    assert "origin/feature/RR-00001" in remote_branches


async def test_push_task_repository_skips_when_read_only(tmp_path: Path) -> None:
    origin = _init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_ONLY)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    (target_dir / "new_file.txt").write_text("новый файл\n")
    _run("git", "add", "new_file.txt", cwd=target_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "добавить файл", cwd=target_dir)

    await push_task_repository(
        repository=repository,
        task_repository=task_repository,
        repo_dir=target_dir,
    )

    remote_heads = _run("git", "ls-remote", "--heads", "origin", cwd=target_dir)
    assert "feature/RR-00001" not in remote_heads


async def test_rebase_onto_base_branch_succeeds_without_conflict(tmp_path: Path) -> None:
    origin = _init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )

    # Кто-то ещё обновил base_branch независимо от рабочей ветки задачи.
    updater_dir = tmp_path / "updater"
    _run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "unrelated_file.txt").write_text("не конфликтует\n")
    _run("git", "add", "unrelated_file.txt", cwd=updater_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "апдейт базовой ветки", cwd=updater_dir)
    _run("git", "push", "origin", "main", cwd=updater_dir)

    await rebase_onto_base_branch(
        repository=repository,
        task_repository=task_repository,
        repo_dir=target_dir,
    )

    assert (target_dir / "unrelated_file.txt").exists()


async def test_rebase_onto_base_branch_raises_and_aborts_on_conflict(tmp_path: Path) -> None:
    origin = _init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    (target_dir / "README.md").write_text("изменение из рабочей ветки задачи\n")
    _run("git", "add", "README.md", cwd=target_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "правка в задаче", cwd=target_dir)

    updater_dir = tmp_path / "updater"
    _run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "README.md").write_text("конфликтующее изменение базовой ветки\n")
    _run("git", "add", "README.md", cwd=updater_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "конфликтующий апдейт", cwd=updater_dir)
    _run("git", "push", "origin", "main", cwd=updater_dir)

    with pytest.raises(RebaseConflictError) as exc_info:
        await rebase_onto_base_branch(
            repository=repository,
            task_repository=task_repository,
            repo_dir=target_dir,
        )

    assert exc_info.value.conflicting_files == ["README.md"]
    # Ребейз обязан быть отменён (--abort) — рабочая директория чистая.
    assert _run("git", "status", "--porcelain", cwd=target_dir).strip() == ""


async def test_run_git_failure_raises_external_service_error(tmp_path: Path) -> None:
    repository = _make_repository(git_url=str(tmp_path / "does-not-exist.git"))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)

    with pytest.raises(ExternalServiceError):
        await clone_task_repository(
            repository=repository,
            task_repository=task_repository,
            task_code="RR-00001",
            repos_root=tmp_path / "repos",
        )
