"""Жизненный цикл задачи: создание, привязка пайплайна, запуск, история,
решения по `awaiting_input`/`plan_review`, библиотека промтов, свободный
промт (раздел 2.3, 2.4, 7, 8, 9.6 ТЗ).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    AwaitingDecisionCountResponse,
    BindPipelineRequest,
    DecisionRequest,
    FreeformPromptRequest,
    LibraryPromptAddRequest,
    ManualRequestResponse,
    NodeLogResponse,
    TaskCreateRequest,
    TaskLibraryPromptResponse,
    TaskResponse,
)
from db.models.enums import NodeLogStatus, TaskStatus
from db.models.logs import NodeLog
from db.models.pipelines import Node, TaskNode
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.tasks import Task
from db.models.users import User
from db.session import get_session
from services.errors import NotFoundError, ValidationError
from services.manual_queue import (
    cancel_manual_request,
    enqueue_freeform_prompt_run,
    enqueue_library_prompt_run,
)
from services.plan_mode import encode_decision
from services.task_signal import publish_task_signal
from services.task_status import transition_task_status
from tasks.session_worker import run_task_session

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_redis_client() -> Redis:
    return Redis.from_url(os.environ["REDIS_URL"])


async def _get_task_or_404(db_session: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await db_session.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"Задача {task_id} не найдена")
    return task


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    body: TaskCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    task = Task(
        id=uuid.uuid4(),
        code=body.code,
        title=body.title,
        description=body.description,
        guide_url=body.guide_url,
        parent_task_id=body.parent_task_id,
        use_parent_summary=body.use_parent_summary,
        created_by=current_user.id,
    )
    db_session.add(task)
    await db_session.commit()
    return task


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
    status_filter: TaskStatus | None = None,
) -> list[Task]:
    stmt = sa.select(Task).order_by(Task.created_at.desc())
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/awaiting-count", response_model=AwaitingDecisionCountResponse)
async def get_awaiting_decision_count(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> AwaitingDecisionCountResponse:
    """Раздел 18.3: постоянный счётчик задач, ожидающих решения."""
    stmt = sa.select(sa.func.count()).where(
        Task.status.in_((TaskStatus.AWAITING_INPUT, TaskStatus.PLAN_REVIEW)),
    )
    count = (await db_session.execute(stmt)).scalar_one()
    return AwaitingDecisionCountResponse(count=count)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    return await _get_task_or_404(db_session, task_id)


@router.post("/{task_id}/pipeline", response_model=TaskResponse)
async def bind_pipeline(
    task_id: uuid.UUID,
    body: BindPipelineRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 3.1, правило 10 CLAUDE.md: создание `task_nodes` и обновление
    `tasks.pipeline_id` — атомарно, в одной транзакции."""
    task = await _get_task_or_404(db_session, task_id)
    if task.status is not TaskStatus.NEW:
        raise ValidationError("Пайплайн можно привязать только к задаче в статусе new")

    nodes_stmt = (
        sa.select(Node)
        .where(Node.pipeline_id == body.pipeline_id)
        .order_by(Node.order_index)
    )
    nodes = list((await db_session.execute(nodes_stmt)).scalars().all())
    if not nodes:
        raise ValidationError("У пайплайна нет нод либо он не существует")

    task.pipeline_id = body.pipeline_id
    for node in nodes:
        db_session.add(
            TaskNode(task_id=task.id, node_id=node.id, order_index=node.order_index or 0),
        )
    await db_session.commit()
    # `updated_at` — колонка с `onupdate=sa.func.now()` (не `server_default`):
    # значение, вычисленное сервером при UPDATE, не возвращается автоматически
    # через RETURNING для обычного ORM-flush'а (в отличие от INSERT) — без
    # явного refresh атрибут остаётся "expired", и синхронная сериализация
    # Pydantic-ответа падает с `MissingGreenlet` при попытке лениво его подгрузить.
    await db_session.refresh(task)
    return task


@router.post("/{task_id}/start", response_model=TaskResponse)
async def start_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 12.2: "тот же процесс запуска, что и ручная кнопка «Выполнить»" —
    `new -> queued`, затем Celery-таск, владеющий сессией, подхватывает
    задачу асинхронно (`tasks/session_worker.py`)."""
    await _get_task_or_404(db_session, task_id)
    updated = await transition_task_status(
        db_session,
        task_id=task_id,
        from_status=TaskStatus.NEW,
        to_status=TaskStatus.QUEUED,
    )

    run_task_session.delay(str(task_id))
    return updated


@router.get("/{task_id}/node-logs", response_model=list[NodeLogResponse])
async def list_node_logs(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[NodeLog]:
    await _get_task_or_404(db_session, task_id)
    stmt = (
        sa.select(NodeLog)
        .where(NodeLog.task_id == task_id)
        .order_by(NodeLog.started_at, NodeLog.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())


@router.post("/{task_id}/decision", status_code=204)
async def submit_decision(
    task_id: uuid.UUID,
    body: DecisionRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 9.6: один и тот же путь для решения по плану И для ответа на
    обычный уточняющий вопрос — атомарно записывает решение и будит
    ожидающий Celery-таск через Redis pub/sub (раздел 9.6, "asyncio.Event/
    эквивалент")."""
    task = await _get_task_or_404(db_session, task_id)
    node_log = await db_session.get(NodeLog, body.node_log_id)
    if node_log is None or node_log.task_id != task.id:
        raise NotFoundError(f"Запись node_logs {body.node_log_id} не найдена у этой задачи")
    if node_log.status is not NodeLogStatus.AWAITING_DECISION:
        raise ValidationError("Эта запись не ожидает решения")

    node_log.user_input_text = encode_decision(body.option_id, feedback_text=body.feedback_text)
    await db_session.commit()

    redis_client = _get_redis_client()
    try:
        await publish_task_signal(redis_client, task_id)
    finally:
        await redis_client.aclose()


@router.post("/{task_id}/freeform", response_model=ManualRequestResponse, status_code=201)
async def submit_freeform_prompt(
    task_id: uuid.UUID,
    body: FreeformPromptRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ManualRequestResponse:
    await _get_task_or_404(db_session, task_id)
    request = await enqueue_freeform_prompt_run(
        db_session,
        task_id=task_id,
        raw_prompt_text=body.raw_prompt_text,
        requested_by=current_user.id,
    )
    await _publish_signal(task_id)
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
    await _get_task_or_404(db_session, task_id)
    node = await db_session.get(Node, body.node_id)
    if node is None:
        raise NotFoundError(f"Промт {body.node_id} не найден")
    task_library_prompt = TaskLibraryPrompt(
        task_id=task_id,
        node_id=body.node_id,
        added_by=current_user.id,
        added_at=datetime.now(UTC),
    )
    db_session.add(task_library_prompt)
    await db_session.commit()
    return task_library_prompt


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
    await _get_task_or_404(db_session, task_id)
    task_library_prompt = await db_session.get(TaskLibraryPrompt, task_library_prompt_id)
    if task_library_prompt is None or task_library_prompt.task_id != task_id:
        raise NotFoundError(f"Промт {task_library_prompt_id} не найден у этой задачи")
    node = await db_session.get(Node, task_library_prompt.node_id)
    if node is None:
        raise NotFoundError(f"Нода {task_library_prompt.node_id} не найдена")

    request = await enqueue_library_prompt_run(
        db_session,
        task_library_prompt=task_library_prompt,
        node=node,
        requested_by=current_user.id,
    )
    await _publish_signal(task_id)
    return ManualRequestResponse.model_validate(request)


@router.delete("/{task_id}/manual-queue/{request_id}", status_code=204)
async def cancel_manual_queue_request(
    task_id: uuid.UUID,
    request_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await _get_task_or_404(db_session, task_id)
    request = await db_session.get(TaskManualRequestQueue, request_id)
    if request is None or request.task_id != task_id:
        raise NotFoundError(f"Запрос {request_id} не найден у этой задачи")
    await cancel_manual_request(db_session, request)


async def _publish_signal(task_id: uuid.UUID) -> None:
    redis_client = _get_redis_client()
    try:
        await publish_task_signal(redis_client, task_id)
    finally:
        await redis_client.aclose()
