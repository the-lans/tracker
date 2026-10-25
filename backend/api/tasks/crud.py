"""
Задача: создание (в т. ч. из Jira), копия, правка полей, списки и
карточка (раздел 2.3, 15.1, 15.6 ТЗ).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    AwaitingDecisionCountResponse,
    TaskCreateRequest,
    TaskDuplicateRequest,
    TaskRepositoryResponse,
    TaskResponse,
    TaskUpdateRequest,
)
from api.tasks.common import TASKS_PREFIX, TASKS_TAGS, get_task_or_404
from db.models.enums import TaskStatus
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from db.session import get_session
from services.access import owner_filter
from services.jira_import import jira_issue_url, mark_attachment_copy_pending, validate_issue_key
from services.redis_connection import redis_connection
from services.session_context import list_active_sessions
from services.task_creation import RepositoryAttachment, TaskDraft
from services.task_creation import create_task as create_task_with_repositories
from services.task_duplication import duplicate_task
from services.task_editing import update_task as update_task_fields
from services.task_workspace import load_task_repositories
from tasks.jira_attachments import copy_jira_attachments_to_task

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)


def _draft_from_request(
    body: TaskDuplicateRequest,
    *,
    parent_task_id: uuid.UUID | None = None,
    use_parent_summary: bool = False,
) -> TaskDraft:
    return TaskDraft(
        code=body.code,
        title=body.title,
        description=body.description,
        guide_url=body.guide_url,
        llm_account_id=body.llm_account_id,
        parent_task_id=parent_task_id,
        use_parent_summary=use_parent_summary,
        repositories=[
            RepositoryAttachment(
                repository_id=attached.repository_id,
                role=attached.role,
                base_branch=attached.base_branch,
            )
            for attached in body.repositories
        ],
    )


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    body: TaskCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """
    Раздел 1.2 (сценарий 1): задача сразу с репозиториями и LLM-аккаунтом.
    С ключом Jira (раздел 15.6) — ссылка на задачу Jira; её вложения копирует
    в артефакты фоновая задача.
    """
    if body.parent_task_id is not None:
        # Раздел 19.2: родителем может быть только доступная пользователю задача.
        await get_task_or_404(db_session, body.parent_task_id, current_user)
    draft = _draft_from_request(
        body,
        parent_task_id=body.parent_task_id,
        use_parent_summary=body.use_parent_summary,
    )
    if body.jira_issue_key is not None:
        issue_url = await jira_issue_url(db_session, current_user, body.jira_issue_key)
        draft = replace(draft, jira_issue_url=issue_url)
    task = await create_task_with_repositories(db_session, draft=draft, created_by=current_user.id)
    if body.jira_issue_key is not None:
        async with redis_connection() as redis_client:
            await mark_attachment_copy_pending(redis_client, task.id)
        copy_jira_attachments_to_task.delay(
            str(task.id),
            str(current_user.id),
            validate_issue_key(body.jira_issue_key),
        )
    return task


@router.post("/{task_id}/duplicate", response_model=TaskResponse, status_code=201)
async def duplicate_task_endpoint(
    task_id: uuid.UUID,
    body: TaskDuplicateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2: «Дублировать задачу» из `done`."""
    source = await get_task_or_404(db_session, task_id, current_user)
    return await duplicate_task(
        db_session,
        source=source,
        draft=_draft_from_request(body),
        created_by=current_user.id,
    )


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 12.1, 15.2: автозапуск и поля задачи — пока задача `new`;
    ``auto_accept_plan`` — в любой момент до `done`."""
    task = await get_task_or_404(db_session, task_id, current_user)
    return await update_task_fields(
        db_session,
        task=task,
        changes=body.model_dump(exclude_unset=True),
    )


@router.get("/{task_id}/repositories", response_model=list[TaskRepositoryResponse])
async def list_task_repositories(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskRepository]:
    await get_task_or_404(db_session, task_id, current_user)
    pairs = await load_task_repositories(db_session, task_id)
    return [task_repository for task_repository, _ in pairs]


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    status_filter: TaskStatus | None = None,
) -> list[Task]:
    stmt = (
        sa.select(Task)
        .where(owner_filter(Task.created_by, current_user))
        .order_by(Task.created_at.desc())
    )
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/awaiting-count", response_model=AwaitingDecisionCountResponse)
async def get_awaiting_decision_count(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AwaitingDecisionCountResponse:
    """
    Раздел 18.3: постоянный счётчик задач, ожидающих решения. Считаются
    только собственные задачи — и у `admin` (решение №16 плана): решение по
    чужой задаче принимает её автор, которому и приходит push.
    """
    stmt = sa.select(sa.func.count()).where(
        Task.created_by == current_user.id,
        Task.status.in_((TaskStatus.AWAITING_INPUT, TaskStatus.PLAN_REVIEW)),
    )
    count = (await db_session.execute(stmt)).scalar_one()
    return AwaitingDecisionCountResponse(count=count)


@router.get("/active-sessions", response_model=list[TaskResponse])
async def list_my_active_sessions(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[Task]:
    """Раздел 15.1: активные сессии Claude Code задач текущего пользователя."""
    return await list_active_sessions(db_session, user_id=current_user.id)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    return await get_task_or_404(db_session, task_id, current_user)
