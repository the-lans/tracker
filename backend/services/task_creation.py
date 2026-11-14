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

from db.models.repositories import Repository
from db.models.tasks import Task
from services.access import ensure_llm_account_of_owner
from services.errors import NotFoundError, TaskCodeTakenError, ValidationError
from services.task_categories import (
    apply_category_to_new_task,
    ensure_category_pipeline_usable,
    get_category_of_owner,
)
from services.task_codes import validate_task_code
from services.task_repositories import (
    RepositoryAttachment,
    build_task_repository,
    validate_repository_attachments,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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
    # Раздел 15.7: настройки категории копируются в новую задачу.
    category_id: uuid.UUID | None = None


async def _ensure_exists(
    db_session: AsyncSession,
    model: type[Task],
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
) -> dict[uuid.UUID, Repository]:
    """Проверяет черновик задачи; возвращает её репозитории по id."""
    validate_task_code(draft.code)
    repositories = await validate_repository_attachments(db_session, draft.repositories)
    if draft.llm_account_id is not None:
        # Раздел 19.2: только аккаунт автора — и при дублировании задачи.
        await ensure_llm_account_of_owner(
            db_session,
            draft.llm_account_id,
            owner_id=created_by,
            require_active=True,
        )
    if draft.use_parent_summary and draft.parent_task_id is None:
        raise ValidationError("Саммари родителя требует выбранной родительской задачи")
    if draft.parent_task_id is not None:
        await _ensure_exists(db_session, Task, draft.parent_task_id, "Родительская задача")
    if await _code_is_taken(db_session, draft.code):
        raise _code_taken(draft.code)
    return repositories


async def _code_is_taken(db_session: AsyncSession, code: str) -> bool:
    return await db_session.scalar(sa.select(Task.id).where(Task.code == code)) is not None


def _code_taken(code: str) -> TaskCodeTakenError:
    return TaskCodeTakenError(f"Задача с кодом {code} уже существует")


async def _flush_task(db_session: AsyncSession, task: Task) -> None:
    """
    Одновременное создание с тем же кодом проходит проверку в обоих запросах —
    второй упирается в уникальность `tasks.code`: это тот же 409, а не 500.
    """
    code = task.code
    db_session.add(task)
    try:
        await db_session.flush()
    except sa.exc.IntegrityError as exc:
        await db_session.rollback()
        if await _code_is_taken(db_session, code):
            raise _code_taken(code) from exc
        raise


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
    repositories = await _validate_draft(db_session, draft, created_by=created_by)
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
    await _flush_task(db_session, task)
    for attached in draft.repositories:
        db_session.add(
            build_task_repository(
                task=task,
                attached=attached,
                repository=repositories[attached.repository_id],
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
    category = (
        await get_category_of_owner(db_session, draft.category_id, owner_id=created_by)
        if draft.category_id is not None
        else None
    )
    if category is not None:
        await ensure_category_pipeline_usable(db_session, category)
    task = await add_task_with_repositories(db_session, draft=draft, created_by=created_by)
    if category is not None:
        await apply_category_to_new_task(db_session, task=task, category=category)
    await db_session.commit()
    if category is not None:
        # Поля после вставки — отдельным UPDATE: `updated_at` перечитывается.
        await db_session.refresh(task)
    return task
