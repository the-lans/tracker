"""
Репозитории задачи: привязка при создании (раздел 1.2, сценарий 1) и после
него (раздел 3.2 ТЗ).

Репозиторий добавляют, когда из текста задачи не было ясно, с чем работать:
в «Уточняется», на ноде сбора контекста, на паузе. Клонирует его воркер —
перед прогоном или проходом чата и в точке между нодами
(`services/task_workspace.py::clone_missing_repositories`). Удалить можно
только привязку, которую ещё не склонировали, и только пока воркер задачей не
владеет: иначе удаление гонялось бы с клонированием.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from db.models.enums import RepositoryRole, TaskStatus
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.queries.task_repositories import lock_task_row, select_attached_repository_ids
from services.errors import ConflictError, NotFoundError, ValidationError
from services.repository_validation import validate_branch_name
from services.task_status import PRE_LAUNCH_STATUSES, READ_ONLY_STATUSES
from services.task_workspace import build_branch_name

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Сессией задачи в этих статусах никто не владеет (кроме чата — см. `chat_active`).
REMOVABLE_STATUSES = PRE_LAUNCH_STATUSES | {TaskStatus.FAILED}


@dataclass(frozen=True, slots=True)
class RepositoryAttachment:
    repository_id: uuid.UUID
    role: RepositoryRole
    # `None` — ветка по умолчанию репозитория (раздел 3.1).
    base_branch: str | None = None


async def _get_repository(db_session: AsyncSession, repository_id: uuid.UUID) -> Repository:
    repository = await db_session.get(Repository, repository_id)
    if repository is None:
        raise NotFoundError(f"Репозиторий {repository_id} не найден")
    return repository


async def validate_repository_attachments(
    db_session: AsyncSession,
    attachments: list[RepositoryAttachment],
) -> dict[uuid.UUID, Repository]:
    """
    Базовые ветки, повторы и существование репозиториев — при создании задачи
    и при добавлении репозиториев к ней (раздел 3.2). Возвращает их по id.
    """
    for attached in attachments:
        if attached.base_branch is not None:
            validate_branch_name(attached.base_branch)
    repository_ids = [attached.repository_id for attached in attachments]
    if len(set(repository_ids)) != len(repository_ids):
        raise ValidationError("Репозиторий указан у задачи больше одного раза")
    return {
        repository_id: await _get_repository(db_session, repository_id)
        for repository_id in repository_ids
    }


def build_task_repository(
    *,
    task: Task,
    attached: RepositoryAttachment,
    repository: Repository,
) -> TaskRepository:
    """Привязка с рабочей веткой `feature/<код>` (раздел 3.1)."""
    return TaskRepository(
        task_id=task.id,
        repository_id=attached.repository_id,
        role=attached.role,
        branch_name=build_branch_name(task.code),
        base_branch=attached.base_branch or repository.default_branch,
    )


async def add_task_repositories(
    db_session: AsyncSession,
    *,
    task: Task,
    attachments: list[RepositoryAttachment],
) -> list[TaskRepository]:
    # Захват воркером (compare-and-swap статуса) и запуск чата ждут, пока
    # привязка не добавлена или не удалена.
    await lock_task_row(db_session, task.id)
    if task.status in READ_ONLY_STATUSES:
        raise ConflictError(
            "Задача завершена — репозитории не добавляются. Верните её в статус до запуска",
        )
    repositories = await validate_repository_attachments(db_session, attachments)
    if await select_attached_repository_ids(db_session, task.id) & repositories.keys():
        raise ConflictError("Репозиторий уже привязан к задаче")
    added = [
        build_task_repository(
            task=task,
            attached=attached,
            repository=repositories[attached.repository_id],
        )
        for attached in attachments
    ]
    db_session.add_all(added)
    await db_session.commit()
    return added


async def remove_task_repository(
    db_session: AsyncSession,
    *,
    task: Task,
    task_repository_id: uuid.UUID,
) -> None:
    # Захват воркером (compare-and-swap статуса) и запуск чата ждут, пока
    # привязка не добавлена или не удалена.
    await lock_task_row(db_session, task.id)
    task_repository = await db_session.get(TaskRepository, task_repository_id)
    if task_repository is None or task_repository.task_id != task.id:
        raise NotFoundError(f"Репозиторий задачи {task_repository_id} не найден")
    if task_repository.cloned_at is not None:
        raise ConflictError(
            "Репозиторий уже склонирован — привязка остаётся в истории задачи",
        )
    if task.status not in REMOVABLE_STATUSES or task.chat_active:
        raise ConflictError(
            "Убрать репозиторий можно до запуска или в «Ошибке», когда агент не работает",
        )
    await db_session.delete(task_repository)
    await db_session.commit()
