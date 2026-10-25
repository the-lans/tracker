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
    is_rebased_onto_base,
    push_task_repository,
    rebase_onto_base_branch,
)
from tests.git_support import GIT_AUTHOR_ARGS, init_bare_origin, run

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
    origin = init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)

    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )

    assert (target_dir / "README.md").exists()
    current_branch = run("git", "branch", "--show-current", cwd=target_dir).strip()
    assert current_branch == "feature/RR-00001"


async def test_push_task_repository_pushes_when_read_write(tmp_path: Path) -> None:
    origin = init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    (target_dir / "new_file.txt").write_text("новый файл\n")
    run("git", "add", "new_file.txt", cwd=target_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "добавить файл", cwd=target_dir)

    await push_task_repository(
        repository=repository,
        task_repository=task_repository,
        repo_dir=target_dir,
    )

    remote_branches = run("git", "branch", "-r", cwd=target_dir)
    assert "origin/feature/RR-00001" in remote_branches


async def test_push_task_repository_skips_when_read_only(tmp_path: Path) -> None:
    origin = init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_ONLY)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    (target_dir / "new_file.txt").write_text("новый файл\n")
    run("git", "add", "new_file.txt", cwd=target_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "добавить файл", cwd=target_dir)

    await push_task_repository(
        repository=repository,
        task_repository=task_repository,
        repo_dir=target_dir,
    )

    remote_heads = run("git", "ls-remote", "--heads", "origin", cwd=target_dir)
    assert "feature/RR-00001" not in remote_heads


async def test_rebase_onto_base_branch_succeeds_without_conflict(tmp_path: Path) -> None:
    origin = init_bare_origin(tmp_path)
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
    run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "unrelated_file.txt").write_text("не конфликтует\n")
    run("git", "add", "unrelated_file.txt", cwd=updater_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "апдейт базовой ветки", cwd=updater_dir)
    run("git", "push", "origin", "main", cwd=updater_dir)

    await rebase_onto_base_branch(
        repository=repository,
        task_repository=task_repository,
        repo_dir=target_dir,
    )

    assert (target_dir / "unrelated_file.txt").exists()


async def test_rebase_rewrites_commits_without_global_git_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Как в контейнере воркера: глобального git-конфига нет, угадывать
    # идентичность по имени хоста git не должен (macOS делает это молча).
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    origin = init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    # Свой коммит в ветке задачи: без него ребейз — fast-forward и
    # committer-идентичность не нужна.
    (target_dir / "task_file.txt").write_text("работа задачи\n")
    run("git", "add", "task_file.txt", cwd=target_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "правка в задаче", cwd=target_dir)

    updater_dir = tmp_path / "updater"
    run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "unrelated_file.txt").write_text("не конфликтует\n")
    run("git", "add", "unrelated_file.txt", cwd=updater_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "апдейт базовой ветки", cwd=updater_dir)
    run("git", "push", "origin", "main", cwd=updater_dir)

    await rebase_onto_base_branch(
        repository=repository,
        task_repository=task_repository,
        repo_dir=target_dir,
    )

    assert (target_dir / "unrelated_file.txt").exists()
    identities = run("git", "log", "-1", "--format=%ae %ce", cwd=target_dir).split()
    assert identities == ["test@example.com", "tracker@localhost"]


async def test_rebase_onto_base_branch_raises_and_aborts_on_conflict(tmp_path: Path) -> None:
    origin = init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    (target_dir / "README.md").write_text("изменение из рабочей ветки задачи\n")
    run("git", "add", "README.md", cwd=target_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "правка в задаче", cwd=target_dir)

    updater_dir = tmp_path / "updater"
    run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "README.md").write_text("конфликтующее изменение базовой ветки\n")
    run("git", "add", "README.md", cwd=updater_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "конфликтующий апдейт", cwd=updater_dir)
    run("git", "push", "origin", "main", cwd=updater_dir)

    with pytest.raises(RebaseConflictError) as exc_info:
        await rebase_onto_base_branch(
            repository=repository,
            task_repository=task_repository,
            repo_dir=target_dir,
        )

    assert exc_info.value.conflicting_files == ["README.md"]
    # Ребейз обязан быть отменён (--abort) — рабочая директория чистая.
    assert run("git", "status", "--porcelain", cwd=target_dir).strip() == ""


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


def _push_conflicting_base_update(tmp_path: Path, origin: Path) -> None:
    updater_dir = tmp_path / "updater"
    run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "README.md").write_text("конфликтующее изменение базовой ветки\n")
    run("git", "add", "README.md", cwd=updater_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "конфликтующий апдейт", cwd=updater_dir)
    run("git", "push", "origin", "main", cwd=updater_dir)


async def test_is_rebased_onto_base_tracks_rebase_progress(tmp_path: Path) -> None:
    origin = init_bare_origin(tmp_path)
    repository = _make_repository(git_url=str(origin))
    task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
    target_dir = await clone_task_repository(
        repository=repository,
        task_repository=task_repository,
        task_code="RR-00001",
        repos_root=tmp_path / "repos",
    )
    (target_dir / "README.md").write_text("изменение из рабочей ветки задачи\n")
    run("git", "add", "README.md", cwd=target_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "правка в задаче", cwd=target_dir)

    async def check() -> bool:
        return await is_rebased_onto_base(
            repository=repository,
            task_repository=task_repository,
            repo_dir=target_dir,
        )

    assert await check() is True
    _push_conflicting_base_update(tmp_path, origin)
    assert await check() is False, "ветка отстала от обновлённой базы"

    rebase = subprocess.run(
        ["git", *GIT_AUTHOR_ARGS, "rebase", "origin/main"],
        cwd=target_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rebase.returncode != 0
    assert await check() is False, "ребейз остановился на конфликте"

    (target_dir / "README.md").write_text("разрешённый конфликт\n")
    run("git", "add", "README.md", cwd=target_dir)
    run("git", *GIT_AUTHOR_ARGS, "-c", "core.editor=true", "rebase", "--continue", cwd=target_dir)
    assert await check() is True


class TestCloneAfterCleanup:
    async def test_reuses_pushed_work_branch(self, tmp_path: Path) -> None:
        origin = init_bare_origin(tmp_path)
        repository = _make_repository(git_url=str(origin))
        task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
        repos_root = tmp_path / "repos"
        first_clone = await clone_task_repository(
            repository=repository,
            task_repository=task_repository,
            task_code="RR-00001",
            repos_root=repos_root,
        )
        (first_clone / "work.txt").write_text("сделанная работа\n")
        run("git", "add", "work.txt", cwd=first_clone)
        run("git", *GIT_AUTHOR_ARGS, "commit", "-m", "работа", cwd=first_clone)
        await push_task_repository(
            repository=repository,
            task_repository=task_repository,
            repo_dir=first_clone,
        )
        run("rm", "-rf", str(repos_root / "RR-00001"), cwd=tmp_path)

        second_clone = await clone_task_repository(
            repository=repository,
            task_repository=task_repository,
            task_code="RR-00001",
            repos_root=repos_root,
        )

        assert (second_clone / "work.txt").read_text() == "сделанная работа\n"
        current_branch = run("git", "branch", "--show-current", cwd=second_clone).strip()
        assert current_branch == "feature/RR-00001"

    async def test_similar_branch_name_is_not_reused(self, tmp_path: Path) -> None:
        origin = init_bare_origin(tmp_path)
        run("git", "branch", "archive/feature/RR-00001", "main", cwd=origin)
        repository = _make_repository(git_url=str(origin))

        target_dir = await clone_task_repository(
            repository=repository,
            task_repository=_make_task_repository(role=RepositoryRole.READ_WRITE),
            task_code="RR-00001",
            repos_root=tmp_path / "repos",
        )

        current_branch = run("git", "branch", "--show-current", cwd=target_dir).strip()
        assert current_branch == "feature/RR-00001"


class TestUntrustedWorkingCopy:
    """Раздел 19.3: git воркера не исполняет то, что агент или скрипт положили в репозиторий."""

    async def _clone(self, tmp_path: Path) -> tuple[Repository, TaskRepository, Path]:
        origin = init_bare_origin(tmp_path)
        repository = _make_repository(git_url=str(origin))
        task_repository = _make_task_repository(role=RepositoryRole.READ_WRITE)
        target_dir = await clone_task_repository(
            repository=repository,
            task_repository=task_repository,
            task_code="RR-00001",
            repos_root=tmp_path / "repos",
        )
        return repository, task_repository, target_dir

    def _plant_marker_script(self, path: Path, marker: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\ntouch {marker}\n")
        path.chmod(0o755)

    @pytest.mark.parametrize("planted", ["hook", "hooks_path", "fsmonitor"])
    async def test_push_runs_nothing_from_repository(self, tmp_path: Path, planted: str) -> None:
        repository, task_repository, target_dir = await self._clone(tmp_path)
        marker = tmp_path / "executed"
        script = tmp_path / "planted.sh"
        self._plant_marker_script(script, marker)
        if planted == "hook":
            self._plant_marker_script(target_dir / ".git" / "hooks" / "pre-push", marker)
        elif planted == "hooks_path":
            self._plant_marker_script(tmp_path / "hooks" / "pre-push", marker)
            run("git", "config", "core.hooksPath", str(tmp_path / "hooks"), cwd=target_dir)
        else:
            run("git", "config", "core.fsmonitor", str(script), cwd=target_dir)

        await push_task_repository(
            repository=repository,
            task_repository=task_repository,
            repo_dir=target_dir,
        )

        assert not marker.exists()
        assert "origin/feature/RR-00001" in run("git", "branch", "-r", cwd=target_dir)

    async def test_local_config_reduced_to_allowed_keys(self, tmp_path: Path) -> None:
        repository, task_repository, target_dir = await self._clone(tmp_path)
        run("git", "config", "remote.origin.url", str(tmp_path / "elsewhere.git"), cwd=target_dir)
        run("git", "config", "filter.evil.smudge", "touch /tmp/never", cwd=target_dir)
        run("git", "config", "gpg.program", "touch", cwd=target_dir)

        await rebase_onto_base_branch(
            repository=repository,
            task_repository=task_repository,
            repo_dir=target_dir,
        )

        config = run("git", "config", "--local", "--list", cwd=target_dir)
        assert f"remote.origin.url={repository.git_url}" in config
        assert "core.repositoryformatversion=0" in config
        assert "filter.evil" not in config
        assert "gpg.program" not in config
