"""Тесты `services/task_workspace.py`: клон репозиториев задачи, файлы
шаблона, push по завершении (разделы 1.2, 3.1, 11.3, 17.4 ТЗ).

Origin — локальный bare-репозиторий (файловый transport git), как в
`test_git_ops.py`.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from db.models.enums import (
    MergeStatus,
    ParentSummaryStatus,
    RepositoryRole,
    TaskStatus,
    UserRole,
)
from db.models.repositories import Repository, Template
from db.models.tasks import Task, TaskParentSummary, TaskRepository
from db.models.users import User
from services.crypto import encrypt
from services.distributed_lock import LockNotAcquiredError, acquire_task_operation_lock
from services.errors import ConflictError, ValidationError
from services.task_cleanup import cleanup_task_repositories
from services.task_workspace import (
    build_branch_name,
    prepare_task_workspace,
    push_task_workspace,
    write_template_files,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

_GIT_AUTHOR_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]
_UNUSED_DEPLOY_KEY = "не используется файловым transport'ом"


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def _init_bare_origin(tmp_path: Path, name: str) -> Path:
    origin = tmp_path / f"{name}.git"
    _run("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)
    seed_dir = tmp_path / f"{name}-seed"
    _run("git", "clone", str(origin), str(seed_dir), cwd=tmp_path)
    (seed_dir / "README.md").write_text("исходный файл\n")
    _run("git", "add", "README.md", cwd=seed_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "начальный коммит", cwd=seed_dir)
    _run("git", "push", "origin", "main", cwd=seed_dir)
    return origin


async def _make_task(db_session: AsyncSession) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    code = f"RR-{uuid.uuid4().hex[:5]}"
    task = Task(code=code, title="t", description="d", created_by=user.id)
    db_session.add(task)
    await db_session.flush()
    return task


async def _attach_repository(
    db_session: AsyncSession,
    task: Task,
    *,
    origin: Path,
    name: str,
    role: RepositoryRole,
    template: Template | None = None,
) -> TaskRepository:
    repository = Repository(
        name=name,
        git_url=str(origin),
        deploy_key_encrypted=encrypt(_UNUSED_DEPLOY_KEY),
        default_template_id=template.id if template else None,
    )
    db_session.add(repository)
    await db_session.flush()
    task_repository = TaskRepository(
        task_id=task.id,
        repository_id=repository.id,
        role=role,
        branch_name=build_branch_name(task.code),
        base_branch="main",
    )
    db_session.add(task_repository)
    await db_session.flush()
    return task_repository


async def _make_template(db_session: AsyncSession, files: dict[str, object]) -> Template:
    template = Template(name=f"tpl-{uuid.uuid4().hex[:6]}", files=files)
    db_session.add(template)
    await db_session.flush()
    return template


async def test_prepare_clones_repositories_on_task_branch(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task(db_session)
    origin = _init_bare_origin(tmp_path, "backend")
    await _attach_repository(
        db_session,
        task,
        origin=origin,
        name="backend",
        role=RepositoryRole.READ_WRITE,
    )

    root = await prepare_task_workspace(db_session, task=task, repos_root=tmp_path / "repos")

    assert root == tmp_path / "repos" / task.code
    branch = _run("git", "branch", "--show-current", cwd=root / "backend").strip()
    assert branch == f"feature/{task.code}"


async def test_prepare_writes_template_files_to_task_root_not_into_repository(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task(db_session)
    template = await _make_template(
        db_session,
        {
            "CLAUDE.md": "# правила\n",
            ".claude/commands/deploy.md": "Задеплой $1\n",
            ".claude/settings.json": {"permissions": {"allow": ["Bash(git:*)"]}},
        },
    )
    await _attach_repository(
        db_session,
        task,
        origin=_init_bare_origin(tmp_path, "backend"),
        name="backend",
        role=RepositoryRole.READ_WRITE,
        template=template,
    )

    root = await prepare_task_workspace(db_session, task=task, repos_root=tmp_path / "repos")

    assert (root / ".claude/commands/deploy.md").read_text() == "Задеплой $1\n"
    assert '"Bash(git:*)"' in (root / ".claude/settings.json").read_text()
    assert not (root / "backend" / "CLAUDE.md").exists()
    assert _run("git", "status", "--porcelain", cwd=root / "backend") == ""


async def test_prepare_is_idempotent_and_keeps_agent_changes(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task = await _make_task(db_session)
    template = await _make_template(db_session, {"CLAUDE.md": "из шаблона\n"})
    await _attach_repository(
        db_session,
        task,
        origin=_init_bare_origin(tmp_path, "backend"),
        name="backend",
        role=RepositoryRole.READ_WRITE,
        template=template,
    )
    repos_root = tmp_path / "repos"
    root = await prepare_task_workspace(db_session, task=task, repos_root=repos_root)
    (root / "CLAUDE.md").write_text("правка агента\n")
    (root / "backend" / "work.txt").write_text("незакоммиченная работа\n")

    # Повторная подготовка (перезапуск после failed) — без повторного клона.
    await prepare_task_workspace(db_session, task=task, repos_root=repos_root)

    assert (root / "CLAUDE.md").read_text() == "правка агента\n"
    assert (root / "backend" / "work.txt").exists()


@pytest.mark.parametrize("unsafe_path", ["/etc/passwd", "../outside.md", "a/../../b"])
def test_write_template_files_rejects_paths_outside_root(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    with pytest.raises(ValidationError):
        write_template_files(tmp_path, {unsafe_path: "x"})


async def test_push_pushes_read_write_repositories_and_marks_them_pushed(
    db_session: AsyncSession,
    redis_client: Redis,
    tmp_path: Path,
) -> None:
    task = await _make_task(db_session)
    rw_origin = _init_bare_origin(tmp_path, "backend")
    ro_origin = _init_bare_origin(tmp_path, "docs")
    rw = await _attach_repository(
        db_session,
        task,
        origin=rw_origin,
        name="backend",
        role=RepositoryRole.READ_WRITE,
    )
    ro = await _attach_repository(
        db_session,
        task,
        origin=ro_origin,
        name="docs",
        role=RepositoryRole.READ_ONLY,
    )
    repos_root = tmp_path / "repos"
    root = await prepare_task_workspace(db_session, task=task, repos_root=repos_root)
    (root / "backend" / "feature.txt").write_text("результат задачи\n")
    _run("git", "add", "feature.txt", cwd=root / "backend")
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=root / "backend")

    await push_task_workspace(
        db_session,
        task=task,
        repos_root=repos_root,
        redis_client=redis_client,
    )

    branch = f"feature/{task.code}"
    assert _run("git", "branch", "--list", branch, cwd=rw_origin).strip() == branch
    assert _run("git", "branch", "--list", branch, cwd=ro_origin).strip() == ""
    assert rw.merge_status is MergeStatus.PUSHED
    assert rw.pushed_at is not None
    assert ro.merge_status is MergeStatus.NOT_PUSHED


async def test_push_refuses_while_another_push_holds_the_lock(
    db_session: AsyncSession,
    redis_client: Redis,
    tmp_path: Path,
) -> None:
    task = await _make_task(db_session)

    async with acquire_task_operation_lock(redis_client, task_id=task.id, operation="git_push"):
        with pytest.raises(LockNotAcquiredError):
            await push_task_workspace(
                db_session,
                task=task,
                repos_root=tmp_path,
                redis_client=redis_client,
            )


class TestCleanupAndReclone:
    async def test_cleanup_then_prepare_reclones(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        task = await _make_task(db_session)
        task.status = TaskStatus.FAILED
        origin = _init_bare_origin(tmp_path, "backend")
        await _attach_repository(
            db_session,
            task,
            origin=origin,
            name="backend",
            role=RepositoryRole.READ_WRITE,
        )
        repos_root = tmp_path / "repos"
        root = await prepare_task_workspace(db_session, task=task, repos_root=repos_root)
        user_files = tmp_path / "user-files" / task.code
        user_files.mkdir(parents=True)

        await cleanup_task_repositories(db_session, task=task, repos_root=repos_root)

        assert not root.exists()
        assert user_files.exists()
        assert task.repo_cleaned_at is not None

        await prepare_task_workspace(db_session, task=task, repos_root=repos_root)

        assert (root / "backend" / "README.md").exists()
        assert task.repo_cleaned_at is None

    async def test_cleanup_is_repeatable(self, db_session: AsyncSession, tmp_path: Path) -> None:
        task = await _make_task(db_session)
        task.status = TaskStatus.DONE

        await cleanup_task_repositories(db_session, task=task, repos_root=tmp_path)
        await cleanup_task_repositories(db_session, task=task, repos_root=tmp_path)

        assert task.repo_cleaned_at is not None

    @pytest.mark.parametrize(
        "status",
        [TaskStatus.NEW, TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.PAUSED],
    )
    async def test_cleanup_requires_terminal_status(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        status: TaskStatus,
    ) -> None:
        task = await _make_task(db_session)
        task.status = status
        (tmp_path / task.code).mkdir()

        with pytest.raises(ConflictError):
            await cleanup_task_repositories(db_session, task=task, repos_root=tmp_path)

        assert (tmp_path / task.code).exists()
        assert task.repo_cleaned_at is None


class TestCleanupDuringParentSummary:
    @pytest.mark.parametrize(
        ("summary_status", "child_status", "allowed"),
        [
            (ParentSummaryStatus.PENDING, TaskStatus.IN_PROGRESS, False),
            (ParentSummaryStatus.PENDING, TaskStatus.FAILED, True),
            (ParentSummaryStatus.READY, TaskStatus.IN_PROGRESS, True),
        ],
        ids=["summary_running", "child_stopped", "summary_ready"],
    )
    async def test_parent_cleanup(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        summary_status: ParentSummaryStatus,
        child_status: TaskStatus,
        allowed: bool,
    ) -> None:
        """Пока сессия родителя пересказывает историю (ответвление работает в
        его директории), очистка папки родителя запрещена."""
        parent = await _make_task(db_session)
        parent.status = TaskStatus.DONE
        child = await _make_task(db_session)
        child.status = child_status
        db_session.add(
            TaskParentSummary(
                parent_task_id=parent.id,
                child_task_id=child.id,
                status=summary_status,
            ),
        )
        await db_session.flush()
        (tmp_path / parent.code).mkdir()

        if allowed:
            await cleanup_task_repositories(db_session, task=parent, repos_root=tmp_path)
        else:
            with pytest.raises(ConflictError, match="пересказывает"):
                await cleanup_task_repositories(db_session, task=parent, repos_root=tmp_path)

        assert (tmp_path / parent.code).exists() is not allowed
