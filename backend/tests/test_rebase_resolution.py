"""Тесты `services/rebase_resolution.py` — автообработка `rebase_conflict` (раздел 14).

Origin — локальный bare-репозиторий, как в `test_git_ops.py`; «агент» —
`FakeClaudeAgentClient`, чей ``on_query`` делает то, что сделал бы Claude Code.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import NodeLogStatus, NodeLogTriggerType, RepositoryRole, UserRole
from db.models.logs import NodeLog
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from services.crypto import encrypt
from services.rebase_resolution import resolve_rebase_conflict
from services.task_workspace import build_branch_name, prepare_task_workspace
from tests.fakes import FakeClaudeAgentClient, make_result_message

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_GIT_AUTHOR_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]
_NO_EDITOR_ARGS = ["-c", "core.editor=true"]


def _run(*args: str, cwd: Path, check: bool = True) -> str:
    result = subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)
    return result.stdout


def _init_bare_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _run("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)
    seed_dir = tmp_path / "seed"
    _run("git", "clone", str(origin), str(seed_dir), cwd=tmp_path)
    (seed_dir / "README.md").write_text("исходный файл\n")
    _run("git", "add", "README.md", cwd=seed_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "начальный коммит", cwd=seed_dir)
    _run("git", "push", "origin", "main", cwd=seed_dir)
    return origin


def _push_conflicting_base_update(tmp_path: Path, origin: Path) -> None:
    updater_dir = tmp_path / "updater"
    _run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    (updater_dir / "README.md").write_text("изменение родительской задачи\n")
    _run("git", "add", "README.md", cwd=updater_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "смерджен родитель", cwd=updater_dir)
    _run("git", "push", "origin", "main", cwd=updater_dir)


async def _make_task_with_conflicting_branch(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    conflict: bool = True,
) -> tuple[Task, Path]:
    origin = _init_bare_origin(tmp_path)
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(code=f"RR-{uuid.uuid4().hex[:5]}", title="t", description="d", created_by=user.id)
    repository = Repository(
        name="backend",
        git_url=str(origin),
        deploy_key_encrypted=encrypt("не используется"),
    )
    db_session.add_all([task, repository])
    await db_session.flush()
    db_session.add(
        TaskRepository(
            task_id=task.id,
            repository_id=repository.id,
            role=RepositoryRole.READ_WRITE,
            branch_name=build_branch_name(task.code),
            base_branch="main",
        ),
    )
    await db_session.flush()
    workspace = await prepare_task_workspace(db_session, task=task, repos_root=tmp_path / "repos")
    repo_dir = workspace / "backend"
    (repo_dir / "README.md").write_text("изменение дочерней задачи\n")
    _run("git", "add", "README.md", cwd=repo_dir)
    _run("git", *_GIT_AUTHOR_ARGS, "commit", "-m", "работа агента", cwd=repo_dir)
    if conflict:
        _push_conflicting_base_update(tmp_path, origin)
    return task, workspace


async def _logs(db_session: AsyncSession, task: Task) -> list[NodeLog]:
    stmt = sa.select(NodeLog).where(NodeLog.task_id == task.id)
    return list((await db_session.execute(stmt)).scalars().all())


async def test_agent_resolving_conflict_unblocks_task(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task, workspace = await _make_task_with_conflicting_branch(db_session, tmp_path)
    repo_dir = workspace / "backend"

    async def agent_resolves_conflict() -> None:
        _run("git", "fetch", "origin", "main", cwd=repo_dir)
        _run("git", *_GIT_AUTHOR_ARGS, "rebase", "origin/main", cwd=repo_dir, check=False)
        (repo_dir / "README.md").write_text("обе правки объединены\n")
        _run("git", "add", "README.md", cwd=repo_dir)
        _run("git", *_GIT_AUTHOR_ARGS, *_NO_EDITOR_ARGS, "rebase", "--continue", cwd=repo_dir)

    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message()]],
        on_query=agent_resolves_conflict,
    )

    resolved = await resolve_rebase_conflict(
        db_session,
        task=task,
        claude_session=ClaudeCodeSession(fake),
        workspace=workspace,
    )

    assert resolved is True
    assert "backend/" in fake.queries[0]
    assert f"feature/{task.code}" in fake.queries[0]
    [log] = await _logs(db_session, task)
    assert log.trigger_type is NodeLogTriggerType.PIPELINE
    assert log.node_id is None
    assert log.status is NodeLogStatus.SUCCESS


async def test_unresolved_conflict_reports_failure(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task, workspace = await _make_task_with_conflicting_branch(db_session, tmp_path)
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])

    resolved = await resolve_rebase_conflict(
        db_session,
        task=task,
        claude_session=ClaudeCodeSession(fake),
        workspace=workspace,
    )

    assert resolved is False
    [log] = await _logs(db_session, task)
    assert log.status is NodeLogStatus.FAILED


async def test_branch_already_on_base_needs_no_agent(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    task, workspace = await _make_task_with_conflicting_branch(db_session, tmp_path, conflict=False)
    fake = FakeClaudeAgentClient(messages_per_query=[])

    resolved = await resolve_rebase_conflict(
        db_session,
        task=task,
        claude_session=ClaudeCodeSession(fake),
        workspace=workspace,
    )

    assert resolved is True
    assert fake.queries == []
    assert await _logs(db_session, task) == []
