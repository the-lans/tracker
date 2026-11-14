"""CRUD категорий задач (раздел 15.7 ТЗ) — у каждого пользователя свои."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import TaskCategoryRequest, TaskCategoryResponse
from db.models.users import User
from db.session import get_session
from services.access import author_for_user
from services.task_categories import (
    CategoryDraft,
    CategoryView,
    create_category,
    delete_category,
    get_category_of_owner,
    list_categories,
    update_category,
)

router = APIRouter(prefix="/task-categories", tags=["task-categories"])


def _draft(body: TaskCategoryRequest) -> CategoryDraft:
    return CategoryDraft(
        name=body.name,
        pipeline_id=body.pipeline_id,
        auto_accept_plan=body.auto_accept_plan,
        queue_priority=body.queue_priority,
        occupies_slot=body.occupies_slot,
        library_prompt_ids=body.library_prompt_ids,
    )


def _to_response(view: CategoryView) -> TaskCategoryResponse:
    category = view.category
    return TaskCategoryResponse(
        id=category.id,
        name=category.name,
        pipeline_id=category.pipeline_id,
        auto_accept_plan=category.auto_accept_plan,
        library_prompt_ids=view.library_prompt_ids,
        queue_priority=category.queue_priority,
        occupies_slot=category.occupies_slot,
        created_by=category.created_by,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )


@router.get("", response_model=list[TaskCategoryResponse])
async def list_task_categories(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    author_id: uuid.UUID | None = None,
) -> list[TaskCategoryResponse]:
    """
    Свои категории; `admin` — и категории автора чужой задачи (`author_id`),
    чтобы выбрать ей категорию.
    """
    owner_id = author_for_user(author_id, current_user)
    return [_to_response(view) for view in await list_categories(db_session, owner_id=owner_id)]


@router.post("", response_model=TaskCategoryResponse, status_code=201)
async def create_task_category(
    body: TaskCategoryRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskCategoryResponse:
    view = await create_category(db_session, draft=_draft(body), user=current_user)
    return _to_response(view)


@router.put("/{category_id}", response_model=TaskCategoryResponse)
async def update_task_category(
    category_id: uuid.UUID,
    body: TaskCategoryRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskCategoryResponse:
    category = await get_category_of_owner(db_session, category_id, owner_id=current_user.id)
    view = await update_category(
        db_session,
        category=category,
        draft=_draft(body),
        user=current_user,
    )
    return _to_response(view)


@router.delete("/{category_id}", status_code=204)
async def delete_task_category(
    category_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    category = await get_category_of_owner(db_session, category_id, owner_id=current_user.id)
    await delete_category(db_session, category)
