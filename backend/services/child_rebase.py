"""
Ребейз дочерней ветки на новую базу после слияния ветки родителя (раздел
14.1, 16.2 ТЗ, решение №22 плана).

Периодическая задача только отмечает `task_repositories.rebase_requested_at`
(`services/gitlab_sync.py`): в рабочей директории работает агент, и трогать
её может лишь воркер задачи — в точке между нодами, когда ход не идёт. Здесь
— этот ребейз. Незакоммиченные изменения или конфликт помечают репозиторий
`merge_status = conflict`, задача переходит в `rebase_conflict`, и дальше
ветку перебазирует агент (`services/rebase_resolution.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.enums import MergeStatus, TaskStatus
from db.models.repositories import Repository
from db.models.tasks import TaskRepository
from services.errors import ConflictError
from services.git_ops import RebaseConflictError, has_uncommitted_changes, rebase_onto_base_branch
from services.task_status import transition_task_status
from services.task_workspace import load_task_repositories

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

logger = get_logger("child_rebase")

# Раздел 14.1: в `rebase_conflict` задача переходит из работы или паузы.
_CONFLICT_STATUS_SOURCES = frozenset({TaskStatus.IN_PROGRESS, TaskStatus.PAUSED})


async def _requested_rebases(
    db_session: AsyncSession,
    task: Task,
) -> list[tuple[TaskRepository, Repository]]:
    return [
        (task_repository, repository)
        for task_repository, repository in await load_task_repositories(db_session, task.id)
        if task_repository.rebase_requested_at is not None
    ]


async def _rebase_repository(
    *,
    task_repository: TaskRepository,
    repository: Repository,
    repo_dir: Path,
) -> bool:
    """`True` — ребейз сделан или не нужен, `False` — его придётся делать агенту."""
    if not (repo_dir / ".git").exists():
        # Директорию очистили: при следующем клонировании ветка возьмёт новую базу.
        return True
    if await has_uncommitted_changes(repository=repository, repo_dir=repo_dir):
        logger.warning("child_rebase_dirty_tree", task_repository_id=str(task_repository.id))
        return False
    try:
        await rebase_onto_base_branch(
            repository=repository,
            task_repository=task_repository,
            repo_dir=repo_dir,
        )
    except RebaseConflictError:
        return False
    return True


async def _enter_rebase_conflict(db_session: AsyncSession, task: Task) -> None:
    if task.status not in _CONFLICT_STATUS_SOURCES:
        return
    try:
        await transition_task_status(
            db_session,
            task_id=task.id,
            from_status=task.status,
            to_status=TaskStatus.REBASE_CONFLICT,
        )
    except ConflictError:
        # Статус успели сменить — конфликт остаётся признаком в
        # `task_repositories` и разбирается в следующей точке проверки.
        logger.info("child_rebase_conflict_status_changed", task_id=str(task.id))


async def apply_requested_rebases(db_session: AsyncSession, *, task: Task, workspace: Path) -> None:
    """Выполняет ребейзы, запрошенные периодической задачей; отметки снимаются."""
    has_conflict = False
    for task_repository, repository in await _requested_rebases(db_session, task):
        rebased = await _rebase_repository(
            task_repository=task_repository,
            repository=repository,
            repo_dir=workspace / repository.name,
        )
        task_repository.rebase_requested_at = None
        if not rebased:
            task_repository.merge_status = MergeStatus.CONFLICT
            has_conflict = True
        await db_session.commit()
        logger.info(
            "child_rebase_applied",
            task_id=str(task.id),
            task_repository_id=str(task_repository.id),
            rebased=rebased,
        )
    if has_conflict:
        await _enter_rebase_conflict(db_session, task)
