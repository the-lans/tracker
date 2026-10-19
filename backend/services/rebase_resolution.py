"""Автообработка статуса `rebase_conflict` (раздел 14.1, 14.2 ТЗ).

Конфликт обнаруживает периодическая задача (`services/gitlab_sync.py`), но
разрешить его может только агент — в той же сессии задачи, которой владеет
воркер (архитектурное решение А плана реализации). Здесь — один такой
проход: какие репозитории отстали от базовой ветки, промт агенту и
проверка результата. Статус задачи меняет вызывающий воркер.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from db.models.enums import NodeLogStatus, NodeLogTriggerType, RepositoryRole
from db.models.logs import NodeLog
from services.git_ops import is_rebased_onto_base
from services.manual_queue import DEFAULT_FREEFORM_TIMEOUT_SECONDS
from services.nodes.dispatch import execute_llm_node_with_timeout
from services.task_workspace import load_task_repositories

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import ClaudeCodeSession
    from db.models.repositories import Repository
    from db.models.tasks import Task, TaskRepository

logger = get_logger("rebase_resolution")


@dataclass(frozen=True, slots=True)
class OutdatedRepository:
    repository: Repository
    task_repository: TaskRepository
    repo_dir: Path


async def find_outdated_repositories(
    db_session: AsyncSession,
    *,
    task: Task,
    workspace: Path,
) -> list[OutdatedRepository]:
    """Read-write репозитории, чья рабочая ветка не содержит актуальную базу."""
    outdated: list[OutdatedRepository] = []
    for task_repository, repository in await load_task_repositories(db_session, task.id):
        if task_repository.role is not RepositoryRole.READ_WRITE:
            continue
        repo_dir = workspace / repository.name
        if not (repo_dir / ".git").exists():
            continue
        if not await is_rebased_onto_base(
            repository=repository,
            task_repository=task_repository,
            repo_dir=repo_dir,
        ):
            outdated.append(OutdatedRepository(repository, task_repository, repo_dir))
    return outdated


def build_rebase_resolution_prompt(outdated: list[OutdatedRepository]) -> str:
    lines = [
        "Базовая ветка обновилась, и автоматический ребейз рабочей ветки упал на конфликте.",
        "Для каждого репозитория ниже:",
        "1. перейди в его директорию и выполни `git rebase origin/<базовая ветка>`;",
        "2. разреши конфликты, сохранив смысл изменений обеих сторон;",
        "3. заверши ребейз (`git add` и `git rebase --continue`), не используя `--abort`.",
        "",
    ]
    lines.extend(
        f"- `{item.repository.name}/`: ветка `{item.task_repository.branch_name}`, "
        f"база `origin/{item.task_repository.base_branch}`"
        for item in outdated
    )
    return "\n".join(lines)


async def resolve_rebase_conflict(
    db_session: AsyncSession,
    *,
    task: Task,
    claude_session: ClaudeCodeSession,
    workspace: Path,
) -> bool:
    """`True` — все ветки снова на актуальной базе, задача может продолжать.

    Обращение к агенту пишется в `node_logs` (раздел 14.2: «отображение
    прогресса») как пайплайновое без ноды: ни ретраев, ни участия в
    инварианте перехода в `done` у него нет.
    """
    outdated = await find_outdated_repositories(db_session, task=task, workspace=workspace)
    if not outdated:
        logger.info("rebase_conflict_already_resolved", task_id=str(task.id))
        return True

    prompt = build_rebase_resolution_prompt(outdated)
    node_log = NodeLog(
        task_id=task.id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        rendered_prompt=prompt,
        status=NodeLogStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db_session.add(node_log)
    await db_session.commit()

    outcome = await execute_llm_node_with_timeout(
        claude_session,
        prompt,
        timeout_seconds=DEFAULT_FREEFORM_TIMEOUT_SECONDS,
    )
    still_outdated = await find_outdated_repositories(db_session, task=task, workspace=workspace)
    resolved = outcome.success and not still_outdated

    node_log.finished_at = datetime.now(UTC)
    node_log.llm_output_text = outcome.llm_output_text
    node_log.status = NodeLogStatus.SUCCESS if resolved else NodeLogStatus.FAILED
    await db_session.commit()
    logger.info(
        "rebase_conflict_resolution_finished",
        task_id=str(task.id),
        resolved=resolved,
        still_outdated=[item.repository.name for item in still_outdated],
        error=outcome.error_message,
    )
    return resolved
