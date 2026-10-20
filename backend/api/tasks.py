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
    NodeDependentResponse,
    NodeLogResponse,
    TaskCreateRequest,
    TaskLibraryPromptListItem,
    TaskLibraryPromptResponse,
    TaskNodeResponse,
    TaskNodeUpdateRequest,
    TaskRepositoryResponse,
    TaskResponse,
    TaskUpdateRequest,
)
from db.models.enums import ManualRequestStatus, NodeLogStatus, TaskStatus
from db.models.llm import LlmAccount
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from db.session import get_session
from services.errors import ConflictError, NotFoundError, ValidationError
from services.manual_queue import (
    cancel_manual_request,
    enqueue_freeform_prompt_run,
    enqueue_library_prompt_run,
)
from services.node_dependencies import find_task_node_dependents
from services.plan_mode import encode_decision
from services.task_control import TaskControlCommand, request_manual_stop, request_task_control
from services.task_nodes import bind_pipeline_to_task, list_task_nodes, set_task_node_enabled
from services.task_signal import publish_task_signal
from services.task_status import transition_task_status
from services.task_workspace import build_branch_name, load_task_repositories
from tasks.session_worker import run_task_session

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_redis_client() -> Redis:
    return Redis.from_url(os.environ["REDIS_URL"])


async def _get_task_or_404(db_session: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await db_session.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"Задача {task_id} не найдена")
    return task


# Раздел 8.2: ручные промты — «пока сессия активна»; воркер, владеющий
# сессией, существует ровно в этих статусах.
_SESSION_ACTIVE_STATUSES = frozenset(
    {
        TaskStatus.IN_PROGRESS,
        TaskStatus.PAUSED,
        TaskStatus.PLAN_REVIEW,
        TaskStatus.AWAITING_INPUT,
        TaskStatus.REBASE_CONFLICT,
    },
)
_ACTIVE_REQUEST_STATUSES = (ManualRequestStatus.QUEUED, ManualRequestStatus.PROCESSING)


def _require_status(task: Task, allowed: frozenset[TaskStatus], message: str) -> None:
    if task.status not in allowed:
        raise ConflictError(message)


async def _ensure_exists(
    db_session: AsyncSession,
    model: type[LlmAccount] | type[Repository],
    entity_id: uuid.UUID,
    label: str,
) -> None:
    if await db_session.get(model, entity_id) is None:
        raise NotFoundError(f"{label} {entity_id} не найден")


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    body: TaskCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 1.2 (сценарий 1): задача сразу с репозиториями и LLM-аккаунтом.

    Рабочая ветка каждого репозитория — ``feature/{code}`` (раздел 3.1).
    """
    repository_ids = [attached.repository_id for attached in body.repositories]
    if len(set(repository_ids)) != len(repository_ids):
        raise ValidationError("Репозиторий указан у задачи больше одного раза")
    for repository_id in repository_ids:
        await _ensure_exists(db_session, Repository, repository_id, "Репозиторий")
    if body.llm_account_id is not None:
        await _ensure_exists(db_session, LlmAccount, body.llm_account_id, "LLM-аккаунт")

    task = Task(
        id=uuid.uuid4(),
        code=body.code,
        title=body.title,
        description=body.description,
        guide_url=body.guide_url,
        parent_task_id=body.parent_task_id,
        use_parent_summary=body.use_parent_summary,
        llm_account_id=body.llm_account_id,
        created_by=current_user.id,
    )
    db_session.add(task)
    for attached in body.repositories:
        db_session.add(
            TaskRepository(
                task_id=task.id,
                repository_id=attached.repository_id,
                role=attached.role,
                branch_name=build_branch_name(body.code),
                base_branch=attached.base_branch,
            ),
        )
    await db_session.commit()
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 12.1, 15.2: автозапуск и поля задачи — пока задача `new`;
    ``auto_accept_plan`` — в любой момент до `done`."""
    task = await _get_task_or_404(db_session, task_id)
    changes = body.model_dump(exclude_unset=True)
    auto_accept_plan = changes.pop("auto_accept_plan", None)
    if changes and task.status is not TaskStatus.NEW:
        raise ValidationError("Поля задачи можно менять только в статусе new")
    if auto_accept_plan is not None and task.status is TaskStatus.DONE:
        raise ValidationError("Задача уже завершена")
    if changes.get("llm_account_id") is not None:
        await _ensure_exists(db_session, LlmAccount, changes["llm_account_id"], "LLM-аккаунт")

    for field, value in changes.items():
        setattr(task, field, value)
    if auto_accept_plan is not None:
        task.auto_accept_plan = auto_accept_plan
    await db_session.commit()
    await db_session.refresh(task)
    return task


@router.get("/{task_id}/repositories", response_model=list[TaskRepositoryResponse])
async def list_task_repositories(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskRepository]:
    await _get_task_or_404(db_session, task_id)
    pairs = await load_task_repositories(db_session, task_id)
    return [task_repository for task_repository, _ in pairs]


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
    await bind_pipeline_to_task(
        db_session,
        task=task,
        pipeline_id=body.pipeline_id,
        disabled_node_ids=(
            set(body.disabled_node_ids) if body.disabled_node_ids is not None else None
        ),
    )
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


@router.post("/{task_id}/restart", response_model=TaskResponse)
async def restart_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2: «Перезапустить с текущей ноды» — упавшая нода выполняется
    заново, предшествующие ей — нет. Сессия продолжается по сохранённому
    `session_id` (раздел 6.1)."""
    task = await _get_task_or_404(db_session, task_id)
    if task.status is not TaskStatus.FAILED or task.last_failed_order_index is None:
        raise ValidationError("Перезапуск доступен только для задачи в статусе failed")
    run_task_session.delay(
        str(task_id),
        start_after_order_index=task.last_failed_order_index - 1,
    )
    await db_session.refresh(task)
    return task


async def _send_task_control(task_id: uuid.UUID, command: TaskControlCommand) -> None:
    redis_client = _get_redis_client()
    try:
        await request_task_control(redis_client, task_id, command)
    finally:
        await redis_client.aclose()


@router.post("/{task_id}/pause", status_code=202)
async def pause_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 14.2 «Приостановить»: текущая нода дорабатывает, следующая
    не начинается — статус `paused` выставит воркер, владеющий сессией."""
    task = await _get_task_or_404(db_session, task_id)
    _require_status(
        task,
        frozenset({TaskStatus.IN_PROGRESS}),
        "Приостановить можно только выполняющуюся задачу",
    )
    await _send_task_control(task_id, TaskControlCommand.PAUSE)


@router.post("/{task_id}/resume", status_code=202)
async def resume_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    task = await _get_task_or_404(db_session, task_id)
    _require_status(task, frozenset({TaskStatus.PAUSED}), "Задача не на паузе")
    await _send_task_control(task_id, TaskControlCommand.RESUME)


@router.post("/{task_id}/stop", status_code=202)
async def stop_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 14.2 «Остановить»: текущее обращение к сессии прерывается,
    задача переходит в `failed` и перезапускается штатной кнопкой."""
    task = await _get_task_or_404(db_session, task_id)
    _require_status(
        task,
        frozenset({TaskStatus.IN_PROGRESS, TaskStatus.PAUSED}),
        "Остановить можно только выполняющуюся или приостановленную задачу",
    )
    await _send_task_control(task_id, TaskControlCommand.STOP)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_queued_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2 «Отменить постановку»: `queued -> new`. Celery-таск,
    уже стоящий в очереди, проиграет compare-and-swap захвата и ничего не
    сделает. Автозапуск выключается — иначе ближайшая проверка расписания
    (раздел 12.2) поставила бы задачу в очередь снова."""
    await _get_task_or_404(db_session, task_id)
    try:
        updated = await transition_task_status(
            db_session,
            task_id=task_id,
            from_status=TaskStatus.QUEUED,
            to_status=TaskStatus.NEW,
            extra_values={"auto_start_enabled": False},
        )
    except ConflictError as exc:
        raise ConflictError("Задача уже не в очереди — сессия запущена или отменена") from exc
    await db_session.refresh(updated)
    return updated


@router.get("/{task_id}/nodes", response_model=list[TaskNodeResponse])
async def list_nodes_of_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskNodeResponse]:
    task = await _get_task_or_404(db_session, task_id)
    return [
        TaskNodeResponse.model_validate(view) for view in await list_task_nodes(db_session, task)
    ]


@router.patch("/{task_id}/nodes/{task_node_id}", response_model=TaskNodeResponse)
async def update_task_node(
    task_id: uuid.UUID,
    task_node_id: uuid.UUID,
    body: TaskNodeUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> TaskNodeResponse:
    """Раздел 13.1, 13.2 (правило 11 CLAUDE.md)."""
    task = await _get_task_or_404(db_session, task_id)
    await set_task_node_enabled(
        db_session,
        task=task,
        task_node_id=task_node_id,
        is_enabled=body.is_enabled,
    )
    views = await list_task_nodes(db_session, task)
    return TaskNodeResponse.model_validate(next(v for v in views if v.id == task_node_id))


@router.get(
    "/{task_id}/nodes/{task_node_id}/dependents",
    response_model=list[NodeDependentResponse],
)
async def list_task_node_dependents(
    task_id: uuid.UUID,
    task_node_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[NodeDependentResponse]:
    """Раздел 13.3, 15.2: кого затронет отключение ноды — для предупреждения."""
    task = await _get_task_or_404(db_session, task_id)
    dependents = await find_task_node_dependents(
        db_session,
        task=task,
        task_node_id=task_node_id,
    )
    return [NodeDependentResponse.model_validate(node) for node in dependents]


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
    task = await _get_task_or_404(db_session, task_id)
    _require_status(task, _SESSION_ACTIVE_STATUSES, "Сессия задачи не активна (раздел 8.2)")
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
    task = await _get_task_or_404(db_session, task_id)
    _require_status(task, _SESSION_ACTIVE_STATUSES, "Сессия задачи не активна (раздел 8.2)")
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


@router.get("/{task_id}/library-prompts", response_model=list[TaskLibraryPromptListItem])
async def list_library_prompts_of_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskLibraryPromptListItem]:
    """Раздел 7.3, 15.2: таблица системных промтов задачи."""
    await _get_task_or_404(db_session, task_id)
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
            TaskManualRequestQueue.status.in_(_ACTIVE_REQUEST_STATUSES),
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
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskManualRequestQueue]:
    """Раздел 15.2: индикатор «В очереди» — запросы, ещё не завершённые."""
    await _get_task_or_404(db_session, task_id)
    stmt = (
        sa.select(TaskManualRequestQueue)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.status.in_(_ACTIVE_REQUEST_STATUSES),
        )
        .order_by(TaskManualRequestQueue.requested_at)
    )
    return list((await db_session.execute(stmt)).scalars().all())


@router.post("/{task_id}/manual-queue/{request_id}/stop", status_code=202)
async def stop_manual_request(
    task_id: uuid.UUID,
    request_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Кнопка ■ (раздел 7.3): для `queued` — отмена из очереди, для
    выполняющегося запроса — прерывание силами воркера."""
    await _get_task_or_404(db_session, task_id)
    request = await db_session.get(TaskManualRequestQueue, request_id)
    if request is None or request.task_id != task_id:
        raise NotFoundError(f"Запрос {request_id} не найден у этой задачи")
    if request.status is ManualRequestStatus.QUEUED:
        await cancel_manual_request(db_session, request)
        return
    if request.status is not ManualRequestStatus.PROCESSING:
        raise ConflictError("Запрос уже завершён — останавливать нечего")
    redis_client = _get_redis_client()
    try:
        await request_manual_stop(redis_client, task_id, request_id)
    finally:
        await redis_client.aclose()


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
