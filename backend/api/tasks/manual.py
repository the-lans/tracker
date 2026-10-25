"""
Решения в виджете, свободный промт, промты библиотеки и очередь ручных
запросов (раздел 7, 8, 9.6 ТЗ).
"""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    DecisionRequest,
    FreeformPromptRequest,
    LibraryPromptAddRequest,
    ManualRequestResponse,
    TaskLibraryPromptListItem,
    TaskLibraryPromptResponse,
)
from api.tasks.common import (
    ACTIVE_REQUEST_STATUSES,
    TASKS_PREFIX,
    TASKS_TAGS,
    get_task_or_404,
    publish_signal,
    require_status,
)
from db.models.enums import ManualRequestStatus
from db.models.pipelines import Node
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.users import User
from db.session import get_session
from services.access import get_node_for_user, get_or_404, get_task_record_or_404
from services.errors import ConflictError
from services.manual_queue import (
    attach_library_prompt,
    cancel_manual_request,
    enqueue_freeform_prompt_run,
    enqueue_library_prompt_run,
)
from services.plan_mode import record_user_decision
from services.redis_connection import redis_connection
from services.task_control import request_manual_stop
from services.task_status import SESSION_ACTIVE_STATUSES

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)


@router.post("/{task_id}/decision", status_code=204)
async def submit_decision(
    task_id: uuid.UUID,
    body: DecisionRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 9.6: один и тот же путь для решения по плану И для ответа на
    обычный уточняющий вопрос — атомарно записывает решение и будит
    ожидающий Celery-таск через Redis pub/sub (раздел 9.6, "asyncio.Event/
    эквивалент")."""
    task = await get_task_or_404(db_session, task_id, current_user)
    async with redis_connection() as redis_client:
        await record_user_decision(
            db_session,
            task=task,
            node_log_id=body.node_log_id,
            option_id=body.option_id,
            feedback_text=body.feedback_text,
            redis_client=redis_client,
        )


@router.post("/{task_id}/freeform", response_model=ManualRequestResponse, status_code=201)
async def submit_freeform_prompt(
    task_id: uuid.UUID,
    body: FreeformPromptRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ManualRequestResponse:
    task = await get_task_or_404(db_session, task_id, current_user)
    require_status(task, SESSION_ACTIVE_STATUSES, "Сессия задачи не активна (раздел 8.2)")
    request = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task_id,
        raw_prompt_text=body.raw_prompt_text,
        requested_by=current_user.id,
    )
    await publish_signal(task_id)
    return ManualRequestResponse.model_validate(request)


@router.post(
    "/{task_id}/library-prompts",
    response_model=TaskLibraryPromptResponse,
    status_code=201,
)
async def add_library_prompt(
    task_id: uuid.UUID,
    body: LibraryPromptAddRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskLibraryPrompt:
    await get_task_or_404(db_session, task_id, current_user)
    node = await get_node_for_user(db_session, body.node_id, user=current_user)
    return await attach_library_prompt(
        db_session,
        task_id=task_id,
        node=node,
        added_by=current_user.id,
    )


@router.post(
    "/{task_id}/library-prompts/{task_library_prompt_id}/run",
    response_model=ManualRequestResponse,
    status_code=201,
)
async def run_library_prompt(
    task_id: uuid.UUID,
    task_library_prompt_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ManualRequestResponse:
    task = await get_task_or_404(db_session, task_id, current_user)
    require_status(task, SESSION_ACTIVE_STATUSES, "Сессия задачи не активна (раздел 8.2)")
    task_library_prompt = await get_task_record_or_404(
        db_session,
        TaskLibraryPrompt,
        task_library_prompt_id,
        task_id=task_id,
        not_found=f"Промт {task_library_prompt_id} не найден у этой задачи",
    )
    node = await get_or_404(
        db_session,
        Node,
        task_library_prompt.node_id,
        not_found=f"Нода {task_library_prompt.node_id} не найдена",
    )

    request = await enqueue_library_prompt_run(
        db_session,
        task_library_prompt=task_library_prompt,
        node=node,
        requested_by=current_user.id,
    )
    await publish_signal(task_id)
    return ManualRequestResponse.model_validate(request)


@router.get("/{task_id}/library-prompts", response_model=list[TaskLibraryPromptListItem])
async def list_library_prompts_of_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskLibraryPromptListItem]:
    """Раздел 7.3, 15.2: таблица системных промтов задачи."""
    await get_task_or_404(db_session, task_id, current_user)
    stmt = (
        sa.select(TaskLibraryPrompt, Node)
        .join(Node, Node.id == TaskLibraryPrompt.node_id)
        .where(TaskLibraryPrompt.task_id == task_id)
        .order_by(TaskLibraryPrompt.added_at)
    )
    rows = (await db_session.execute(stmt)).all()
    active_stmt = (
        sa.select(TaskManualRequestQueue.node_id, TaskManualRequestQueue.id)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.node_id.is_not(None),
            TaskManualRequestQueue.status.in_(ACTIVE_REQUEST_STATUSES),
        )
        .order_by(TaskManualRequestQueue.requested_at)
    )
    # Самый старый активный запрос промта — тот, что выполнится (или
    # выполняется) первым: его и останавливает кнопка ■.
    active_by_node: dict[uuid.UUID, uuid.UUID] = {}
    for node_id, request_id in (await db_session.execute(active_stmt)).all():
        if node_id is not None:
            active_by_node.setdefault(node_id, request_id)
    return [
        TaskLibraryPromptListItem(
            id=task_library_prompt.id,
            node_id=node.id,
            last_run_status=task_library_prompt.last_run_status,
            last_run_at=task_library_prompt.last_run_at,
            name=node.name,
            node_type=node.node_type,
            active_request_id=active_by_node.get(node.id),
        )
        for task_library_prompt, node in rows
    ]


@router.get("/{task_id}/manual-queue", response_model=list[ManualRequestResponse])
async def list_active_manual_requests(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskManualRequestQueue]:
    """Раздел 15.2: индикатор «В очереди» — запросы, ещё не завершённые."""
    await get_task_or_404(db_session, task_id, current_user)
    stmt = (
        sa.select(TaskManualRequestQueue)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.status.in_(ACTIVE_REQUEST_STATUSES),
        )
        .order_by(TaskManualRequestQueue.requested_at)
    )
    return list((await db_session.execute(stmt)).scalars().all())


@router.post("/{task_id}/manual-queue/{request_id}/stop", status_code=202)
async def stop_manual_request(
    task_id: uuid.UUID,
    request_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Кнопка ■ (раздел 7.3): для `queued` — отмена из очереди, для
    выполняющегося запроса — прерывание силами воркера."""
    await get_task_or_404(db_session, task_id, current_user)
    request = await get_task_record_or_404(
        db_session,
        TaskManualRequestQueue,
        request_id,
        task_id=task_id,
        not_found=f"Запрос {request_id} не найден у этой задачи",
    )
    if request.status is ManualRequestStatus.QUEUED:
        await cancel_manual_request(db_session, request)
        return
    if request.status is not ManualRequestStatus.PROCESSING:
        raise ConflictError("Запрос уже завершён — останавливать нечего")
    async with redis_connection() as redis_client:
        await request_manual_stop(redis_client, task_id, request_id)


@router.delete("/{task_id}/manual-queue/{request_id}", status_code=204)
async def cancel_manual_queue_request(
    task_id: uuid.UUID,
    request_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await get_task_or_404(db_session, task_id, current_user)
    request = await get_task_record_or_404(
        db_session,
        TaskManualRequestQueue,
        request_id,
        task_id=task_id,
        not_found=f"Запрос {request_id} не найден у этой задачи",
    )
    await cancel_manual_request(db_session, request)
