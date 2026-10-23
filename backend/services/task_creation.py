"""
Создание задачи вместе с репозиториями (раздел 1.2, сценарий 1; 3.1 ТЗ).

Общая часть для «Новой задачи» и «Дублировать задачу» (раздел 14.2):
проверки ссылок и уникальности кода, рабочая ветка ``feature/{code}``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import RepositoryRole
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from services.access import ensure_llm_account_of_owner
from services.errors import ConflictError, NotFoundError, ValidationError
from services.repository_validation import validate_branch_name
from services.task_codes import validate_task_code
from services.task_workspace import build_branch_name

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class RepositoryAttachment:
    repository_id: uuid.UUID
    role: RepositoryRole
    base_branch: str


@dataclass(frozen=True, slots=True)
class TaskDraft:
    code: str
    title: str
    description: str
    guide_url: str | None = None
    llm_account_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None
    use_parent_summary: bool = False
    repositories: list[RepositoryAttachment] = field(default_factory=list)
    # Раздел 15.6: задача Jira, из которой заполнена форма.
    jira_issue_url: str | None = None


async def _ensure_exists(
    db_session: AsyncSession,
    model: type[Repository] | type[Task],
    entity_id: uuid.UUID,
    label: str,
) -> None:
    if await db_session.get(model, entity_id) is None:
        raise NotFoundError(f"{label} {entity_id} не найден")


async def _validate_draft(
    db_session: AsyncSession,
    draft: TaskDraft,
    *,
    created_by: uuid.UUID,
) -> None:
    validate_task_code(draft.code)
    for attached in draft.repositories:
        validate_branch_name(attached.base_branch)
    repository_ids = [attached.repository_id for attached in draft.repositories]
    if len(set(repository_ids)) != len(repository_ids):
        raise ValidationError("Репозиторий указан у задачи больше одного раза")
    for repository_id in repository_ids:
        await _ensure_exists(db_session, Repository, repository_id, "Репозиторий")
    if draft.llm_account_id is not None:
        # Раздел 19.2: только аккаунт автора — и при дублировании задачи.
        await ensure_llm_account_of_owner(
            db_session,
            draft.llm_account_id,
            owner_id=created_by,
        )
    if draft.use_parent_summary and draft.parent_task_id is None:
        raise ValidationError("Саммари родителя требует выбранной родительской задачи")
    if draft.parent_task_id is not None:
        await _ensure_exists(db_session, Task, draft.parent_task_id, "Родительская задача")
    code_taken = await db_session.scalar(sa.select(Task.id).where(Task.code == draft.code))
    if code_taken is not None:
        raise ConflictError(f"Задача с кодом {draft.code} уже существует")


async def add_task_with_repositories(
    db_session: AsyncSession,
    *,
    draft: TaskDraft,
    created_by: uuid.UUID,
) -> Task:
    """
    Добавляет задачу и её репозитории в сессию БД без коммита — вызывающий
    код может дописать связанные данные в ту же транзакцию.
    """
    await _validate_draft(db_session, draft, created_by=created_by)
    task = Task(
        id=uuid.uuid4(),
        code=draft.code,
        title=draft.title,
        description=draft.description,
        guide_url=draft.guide_url,
        jira_issue_url=draft.jira_issue_url,
        parent_task_id=draft.parent_task_id,
        use_parent_summary=draft.use_parent_summary,
        llm_account_id=draft.llm_account_id,
        created_by=created_by,
    )
    db_session.add(task)
    for attached in draft.repositories:
        db_session.add(
            TaskRepository(
                task_id=task.id,
                repository_id=attached.repository_id,
                role=attached.role,
                branch_name=build_branch_name(draft.code),
                base_branch=attached.base_branch,
            ),
        )
    await db_session.flush()
    return task


async def create_task(
    db_session: AsyncSession,
    *,
    draft: TaskDraft,
    created_by: uuid.UUID,
) -> Task:
    task = await add_task_with_repositories(db_session, draft=draft, created_by=created_by)
    await db_session.commit()
    return task
