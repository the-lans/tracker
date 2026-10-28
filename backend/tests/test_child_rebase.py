"""
Тесты `services/child_rebase.py`: ребейз дочерней ветки, запрошенный после
слияния ветки родителя, выполняет воркер (раздел 14.1, 16.2 ТЗ).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import MergeStatus, RepositoryRole, TaskStatus
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from services.child_rebase import apply_requested_rebases
from services.crypto import encrypt
from services.task_workspace import build_branch_name, prepare_task_workspace
from tests.factories import make_user
from tests.git_support import commit_file, init_bare_origin, push_base_update, run

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class _ChildTask:
    task: Task
    task_repository: TaskRepository
    repo_dir: Path
    origin: Path


async def _child_task(
    db_session: AsyncSession, tmp_path: Path, *, status: TaskStatus
) -> _ChildTask:
    origin = init_bare_origin(tmp_path)
    user = await make_user(db_session)
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        status=status,
    )
    repository = Repository(name="backend", git_url=str(origin), deploy_key_encrypted=encrypt("k"))
    db_session.add_all([task, repository])
    await db_session.flush()
    task_repository = TaskRepository(
        task_id=task.id,
        repository_id=repository.id,
        role=RepositoryRole.READ_WRITE,
        branch_name=build_branch_name(task.code),
        base_branch="main",
    )
    db_session.add(task_repository)
    await db_session.commit()
    workspace = await prepare_task_workspace(db_session, task=task, repos_root=tmp_path / "repos")
    repo_dir = workspace / "backend"
    commit_file(repo_dir, "README.md", "работа дочерней задачи\n", message="работа агента")
    task_repository.rebase_requested_at = datetime.now(UTC)
    await db_session.commit()
    return _ChildTask(task, task_repository, repo_dir, origin)


async def _apply(db_session: AsyncSession, child: _ChildTask) -> None:
    await apply_requested_rebases(db_session, task=child.task, workspace=child.repo_dir.parent)
    await db_session.refresh(child.task)
    await db_session.refresh(child.task_repository)


class TestApplyRequestedRebases:
    async def test_clean_rebase(self, db_session: AsyncSession, tmp_path: Path) -> None:
        child = await _child_task(db_session, tmp_path, status=TaskStatus.IN_PROGRESS)
        push_base_update(tmp_path, child.origin, "other.txt", "не конфликтует\n")

        await _apply(db_session, child)

        assert (child.repo_dir / "other.txt").exists()
        assert child.task_repository.rebase_requested_at is None
        assert child.task_repository.merge_status is MergeStatus.NOT_PUSHED
        assert child.task.status is TaskStatus.IN_PROGRESS

    async def test_untracked_files_kept(self, db_session: AsyncSession, tmp_path: Path) -> None:
        """Вывод тестов (`__pycache__/`) — не незакоммиченная работа: ребейз без агента."""
        child = await _child_task(db_session, tmp_path, status=TaskStatus.PAUSED)
        (child.repo_dir / "__pycache__").mkdir()
        (child.repo_dir / "__pycache__" / "calc.pyc").write_bytes(b"\x00")
        push_base_update(tmp_path, child.origin, "other.txt", "не конфликтует\n")

        await _apply(db_session, child)

        assert (child.repo_dir / "other.txt").exists()
        assert (child.repo_dir / "__pycache__" / "calc.pyc").exists()
        assert child.task.status is TaskStatus.PAUSED

    @pytest.mark.parametrize("cause", ["conflict", "dirty_tree", "untracked_collision"])
    @pytest.mark.parametrize("status", [TaskStatus.IN_PROGRESS, TaskStatus.PAUSED])
    async def test_left_to_agent(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
        cause: str,
        status: TaskStatus,
    ) -> None:
        child = await _child_task(db_session, tmp_path, status=status)
        if cause == "conflict":
            push_base_update(tmp_path, child.origin, "README.md", "правка базы\n")
        elif cause == "dirty_tree":
            (child.repo_dir / "README.md").write_text("незакоммиченная работа агента\n")
        else:
            push_base_update(tmp_path, child.origin, "draft.txt", "файл базы\n")
            (child.repo_dir / "draft.txt").write_text("неотслеживаемая работа агента\n")

        await _apply(db_session, child)

        assert child.task_repository.rebase_requested_at is None
        assert child.task_repository.merge_status is MergeStatus.CONFLICT
        assert child.task.status is TaskStatus.REBASE_CONFLICT
        # Работа агента не потеряна, ребейз не остался висеть.
        assert run("git", "status", "--porcelain", cwd=child.repo_dir).strip() in (
            "",
            "M README.md",
            "?? draft.txt",
        )
        assert not (child.repo_dir / ".git" / "rebase-merge").exists()

    async def test_requested_by_other_process(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        """
        Флаг ставит периодическая задача в своей сессии БД, а запись уже
        загружена в долгоживущую сессию воркера без флага.
        """
        child = await _child_task(db_session, tmp_path, status=TaskStatus.IN_PROGRESS)
        child.task_repository.rebase_requested_at = None
        await db_session.commit()
        await db_session.execute(
            sa.update(TaskRepository)
            .where(TaskRepository.id == child.task_repository.id)
            .values(rebase_requested_at=datetime.now(UTC))
            .execution_options(synchronize_session=False),
        )
        push_base_update(tmp_path, child.origin, "other.txt", "не конфликтует\n")

        await _apply(db_session, child)

        assert (child.repo_dir / "other.txt").exists()
        assert child.task_repository.rebase_requested_at is None

    async def test_nothing_requested(self, db_session: AsyncSession, tmp_path: Path) -> None:
        child = await _child_task(db_session, tmp_path, status=TaskStatus.IN_PROGRESS)
        child.task_repository.rebase_requested_at = None
        await db_session.commit()
        push_base_update(tmp_path, child.origin, "README.md", "правка базы\n")

        await _apply(db_session, child)

        assert child.task_repository.merge_status is MergeStatus.NOT_PUSHED
        assert child.task.status is TaskStatus.IN_PROGRESS

