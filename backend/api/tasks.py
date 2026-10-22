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
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    ArtifactResponse,
    AwaitingDecisionCountResponse,
    BindPipelineRequest,
    DecisionRequest,
    EnvVariableRevealResponse,
    FreeformPromptRequest,
    LibraryPromptAddRequest,
    ManualRequestResponse,
    NodeDependentResponse,
    NodeLogResponse,
    TaskCreateRequest,
    TaskDuplicateRequest,
    TaskEnvVariableCreateRequest,
    TaskEnvVariableResponse,
    TaskEnvVariableUpdateRequest,
    TaskLibraryPromptListItem,
    TaskLibraryPromptResponse,
    TaskNodeResponse,
    TaskNodeUpdateRequest,
    TaskRepositoryResponse,
    TaskResponse,
    TaskUpdateRequest,
)
from db.models.enums import (
    ManualRequestStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    TaskStatus,
)
from db.models.env_vars import TaskEnvVariable
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.tasks import Task, TaskRepository
from db.models.users import User
from db.session import get_session
from services.access import (
    ensure_llm_account_of_owner,
    get_node_for_user,
    get_pipeline_for_user,
    get_task_for_user,
    owner_filter,
)
from services.errors import ConflictError, NotFoundError, ValidationError
from services.integrity import ensure_library_prompt_attachable, ensure_pipeline_attachable
from services.manual_queue import (
    cancel_manual_request,
    enqueue_freeform_prompt_run,
    enqueue_library_prompt_run,
)
from services.node_dependencies import find_task_node_dependents
from services.plan_mode import encode_decision
from services.remote_control import start_bridge_reconnect
from services.session_context import clear_task_session_context, list_active_sessions
from services.task_artifacts import (
    ArtifactInfo,
    artifact_file,
    delete_artifact,
    list_artifacts,
    max_upload_bytes,
    save_artifact,
)
from services.task_cleanup import cleanup_task_repositories
from services.task_control import (
    TaskControlCommand,
    request_manual_stop,
    request_task_control,
)
from services.task_creation import RepositoryAttachment, TaskDraft
from services.task_creation import create_task as create_task_with_repositories
from services.task_duplication import duplicate_task
from services.task_env_variables import (
    create_task_env_variable,
    delete_task_env_variable,
    list_task_env_variables,
    reveal_task_env_variable,
    update_task_env_variable,
)
from services.task_nodes import bind_pipeline_to_task, list_task_nodes, set_task_node_enabled
from services.task_signal import publish_task_signal
from services.task_status import SESSION_ACTIVE_STATUSES, transition_task_status
from services.task_workspace import load_task_repositories, resolve_repos_root
from services.template_context import ensure_no_repository_env_conflicts
from tasks.session_worker import run_task_session

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_redis_client() -> Redis:
    return Redis.from_url(os.environ["REDIS_URL"])


async def _get_task_or_404(db_session: AsyncSession, task_id: uuid.UUID, user: User) -> Task:
    """Раздел 19.2: чужая задача для `user` неотличима от несуществующей."""
    return await get_task_for_user(db_session, task_id, user=user)


_ACTIVE_REQUEST_STATUSES = (ManualRequestStatus.QUEUED, ManualRequestStatus.PROCESSING)


def _require_status(task: Task, allowed: frozenset[TaskStatus], message: str) -> None:
    if task.status not in allowed:
        raise ConflictError(message)


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
    """Раздел 1.2 (сценарий 1): задача сразу с репозиториями и LLM-аккаунтом."""
    if body.parent_task_id is not None:
        # Раздел 19.2: родителем может быть только доступная пользователю задача.
        await _get_task_or_404(db_session, body.parent_task_id, current_user)
    draft = _draft_from_request(
        body,
        parent_task_id=body.parent_task_id,
        use_parent_summary=body.use_parent_summary,
    )
    return await create_task_with_repositories(db_session, draft=draft, created_by=current_user.id)


@router.post("/{task_id}/duplicate", response_model=TaskResponse, status_code=201)
async def duplicate_task_endpoint(
    task_id: uuid.UUID,
    body: TaskDuplicateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2: «Дублировать задачу» из `done`."""
    source = await _get_task_or_404(db_session, task_id, current_user)
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
    task = await _get_task_or_404(db_session, task_id, current_user)
    changes = body.model_dump(exclude_unset=True)
    auto_accept_plan = changes.pop("auto_accept_plan", None)
    if changes and task.status is not TaskStatus.NEW:
        raise ValidationError("Поля задачи можно менять только в статусе new")
    if auto_accept_plan is not None and task.status is TaskStatus.DONE:
        raise ValidationError("Задача уже завершена")
    if changes.get("llm_account_id") is not None:
        # Раздел 19.2: аккаунт автора задачи, даже если меняет `admin`.
        await ensure_llm_account_of_owner(
            db_session,
            changes["llm_account_id"],
            owner_id=task.created_by,
        )

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
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskRepository]:
    await _get_task_or_404(db_session, task_id, current_user)
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
    return await _get_task_or_404(db_session, task_id, current_user)


@router.post("/{task_id}/pipeline", response_model=TaskResponse)
async def bind_pipeline(
    task_id: uuid.UUID,
    body: BindPipelineRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 3.1, правило 10 CLAUDE.md: создание `task_nodes` и обновление
    `tasks.pipeline_id` — атомарно, в одной транзакции."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    pipeline = await get_pipeline_for_user(db_session, body.pipeline_id, user=current_user)
    ensure_pipeline_attachable(pipeline)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 12.2: "тот же процесс запуска, что и ручная кнопка «Выполнить»" —
    `new -> queued`, затем Celery-таск, владеющий сессией, подхватывает
    задачу асинхронно (`tasks/session_worker.py`)."""
    await _get_task_or_404(db_session, task_id, current_user)
    await ensure_no_repository_env_conflicts(db_session, task_id=task_id)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2: «Перезапустить с текущей ноды» — упавшая нода выполняется
    заново, предшествующие ей — нет. Сессия продолжается по сохранённому
    `session_id` (раздел 6.1)."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    if task.status is not TaskStatus.FAILED or task.last_failed_order_index is None:
        raise ValidationError("Перезапуск доступен только для задачи в статусе failed")
    await ensure_no_repository_env_conflicts(db_session, task_id=task_id)
    run_task_session.delay(
        str(task_id),
        start_after_order_index=task.last_failed_order_index - 1,
    )
    await db_session.refresh(task)
    return task


@router.post("/{task_id}/cleanup-repositories", response_model=TaskResponse)
async def cleanup_repositories(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """
    Раздел 14.3: удаление рабочей директории репозиториев — только вручную
    и только в `done`/`failed`; пользовательские файлы не затрагиваются.
    """
    task = await _get_task_or_404(db_session, task_id, current_user)
    await cleanup_task_repositories(db_session, task=task, repos_root=resolve_repos_root())
    await db_session.refresh(task)
    return task


@router.post("/{task_id}/clear-context", response_model=TaskResponse)
async def clear_context(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2: «очистить контекст» в `failed` — перезапуск начнёт новую сессию."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    await clear_task_session_context(db_session, task=task)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 14.2 «Приостановить»: текущая нода дорабатывает, следующая
    не начинается — статус `paused` выставит воркер, владеющий сессией."""
    task = await _get_task_or_404(db_session, task_id, current_user)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    task = await _get_task_or_404(db_session, task_id, current_user)
    _require_status(task, frozenset({TaskStatus.PAUSED}), "Задача не на паузе")
    await _send_task_control(task_id, TaskControlCommand.RESUME)


@router.post("/{task_id}/stop", status_code=202)
async def stop_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 14.2 «Остановить»: текущее обращение к сессии прерывается,
    задача переходит в `failed` и перезапускается штатной кнопкой."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    _require_status(
        task,
        frozenset({TaskStatus.IN_PROGRESS, TaskStatus.PAUSED}),
        "Остановить можно только выполняющуюся или приостановленную задачу",
    )
    await _send_task_control(task_id, TaskControlCommand.STOP)


@router.post("/{task_id}/remote-control/reconnect", status_code=202)
async def reconnect_remote_control(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """
    Раздел 6.5: новая попытка поднять мост `/remote-control`. Сессией
    владеет воркер — он пересоздаст процесс CLI между ходами и обновит
    `remote_control_status`; восстановление моста не гарантируется.
    """
    task = await _get_task_or_404(db_session, task_id, current_user)
    redis_client = _get_redis_client()
    try:
        await start_bridge_reconnect(db_session, task=task, redis_client=redis_client)
    finally:
        await redis_client.aclose()


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_queued_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2 «Отменить постановку»: `queued -> new`. Celery-таск,
    уже стоящий в очереди, проиграет compare-and-swap захвата и ничего не
    сделает. Автозапуск выключается — иначе ближайшая проверка расписания
    (раздел 12.2) поставила бы задачу в очередь снова."""
    await _get_task_or_404(db_session, task_id, current_user)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskNodeResponse]:
    task = await _get_task_or_404(db_session, task_id, current_user)
    return [
        TaskNodeResponse.model_validate(view) for view in await list_task_nodes(db_session, task)
    ]


@router.patch("/{task_id}/nodes/{task_node_id}", response_model=TaskNodeResponse)
async def update_task_node(
    task_id: uuid.UUID,
    task_node_id: uuid.UUID,
    body: TaskNodeUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskNodeResponse:
    """Раздел 13.1, 13.2 (правило 11 CLAUDE.md)."""
    task = await _get_task_or_404(db_session, task_id, current_user)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[NodeDependentResponse]:
    """Раздел 13.3, 15.2: кого затронет отключение ноды — для предупреждения."""
    task = await _get_task_or_404(db_session, task_id, current_user)
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
    current_user: Annotated[User, Depends(get_current_user)],
    node_id: uuid.UUID | None = None,
    status: NodeLogStatus | None = None,
    trigger_type: NodeLogTriggerType | None = None,
) -> list[NodeLog]:
    """
    Раздел 13.4: история выполнения — лента и вкладка «Логи» с фильтрами
    по ноде, статусу и источнику.
    """
    await _get_task_or_404(db_session, task_id, current_user)
    stmt = (
        sa.select(NodeLog)
        .where(NodeLog.task_id == task_id)
        .order_by(NodeLog.started_at, NodeLog.id)
    )
    filters = {NodeLog.node_id: node_id, NodeLog.status: status, NodeLog.trigger_type: trigger_type}
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(column == value)
    return list((await db_session.execute(stmt)).scalars().all())


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
    task = await _get_task_or_404(db_session, task_id, current_user)
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
    task = await _get_task_or_404(db_session, task_id, current_user)
    _require_status(task, SESSION_ACTIVE_STATUSES, "Сессия задачи не активна (раздел 8.2)")
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
    await _get_task_or_404(db_session, task_id, current_user)
    node = await get_node_for_user(db_session, body.node_id, user=current_user)
    ensure_library_prompt_attachable(node)
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
    task = await _get_task_or_404(db_session, task_id, current_user)
    _require_status(task, SESSION_ACTIVE_STATUSES, "Сессия задачи не активна (раздел 8.2)")
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskLibraryPromptListItem]:
    """Раздел 7.3, 15.2: таблица системных промтов задачи."""
    await _get_task_or_404(db_session, task_id, current_user)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskManualRequestQueue]:
    """Раздел 15.2: индикатор «В очереди» — запросы, ещё не завершённые."""
    await _get_task_or_404(db_session, task_id, current_user)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Кнопка ■ (раздел 7.3): для `queued` — отмена из очереди, для
    выполняющегося запроса — прерывание силами воркера."""
    await _get_task_or_404(db_session, task_id, current_user)
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await _get_task_or_404(db_session, task_id, current_user)
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


@router.get("/{task_id}/env-variables", response_model=list[TaskEnvVariableResponse])
async def list_env_variables_of_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TaskEnvVariable]:
    """Раздел 15.2: переменные в зоне статичных данных задачи."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    return await list_task_env_variables(db_session, task)


@router.post(
    "/{task_id}/env-variables",
    response_model=TaskEnvVariableResponse,
    status_code=201,
)
async def create_env_variable_of_task(
    task_id: uuid.UUID,
    body: TaskEnvVariableCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskEnvVariable:
    task = await _get_task_or_404(db_session, task_id, current_user)
    return await create_task_env_variable(
        db_session,
        task=task,
        key=body.key,
        value=body.value,
    )


@router.patch(
    "/{task_id}/env-variables/{variable_id}",
    response_model=TaskEnvVariableResponse,
)
async def update_env_variable_of_task(
    task_id: uuid.UUID,
    variable_id: uuid.UUID,
    body: TaskEnvVariableUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TaskEnvVariable:
    task = await _get_task_or_404(db_session, task_id, current_user)
    return await update_task_env_variable(
        db_session,
        task=task,
        variable_id=variable_id,
        value=body.value,
    )


@router.delete("/{task_id}/env-variables/{variable_id}", status_code=204)
async def delete_env_variable_of_task(
    task_id: uuid.UUID,
    variable_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    task = await _get_task_or_404(db_session, task_id, current_user)
    await delete_task_env_variable(db_session, task=task, variable_id=variable_id)


@router.get(
    "/{task_id}/env-variables/{variable_id}/reveal",
    response_model=EnvVariableRevealResponse,
)
async def reveal_env_variable_of_task(
    task_id: uuid.UUID,
    variable_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> EnvVariableRevealResponse:
    """Правило 8: значение — только по явному запросу «Показать»."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    value = await reveal_task_env_variable(db_session, task=task, variable_id=variable_id)
    return EnvVariableRevealResponse(value=value)


@router.get("/{task_id}/artifacts", response_model=list[ArtifactResponse])
async def list_task_artifacts(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ArtifactInfo]:
    """Раздел 14.3, 15.2: артефакты задачи — в любом её статусе."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    return list_artifacts(task.code)


@router.put("/{task_id}/artifacts/{path:path}", response_model=ArtifactResponse, status_code=201)
async def upload_task_artifact(
    task_id: uuid.UUID,
    path: str,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ArtifactInfo:
    """Тело запроса — содержимое файла целиком; существующий файл заменяется."""
    task = await _get_task_or_404(db_session, task_id, current_user)
    return await save_artifact(task.code, path, request.stream(), max_bytes=max_upload_bytes())


@router.get("/{task_id}/artifacts/{path:path}")
async def download_task_artifact(
    task_id: uuid.UUID,
    path: str,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    task = await _get_task_or_404(db_session, task_id, current_user)
    target = artifact_file(task.code, path)
    return FileResponse(target, filename=target.name)


@router.delete("/{task_id}/artifacts/{path:path}", status_code=204)
async def delete_task_artifact(
    task_id: uuid.UUID,
    path: str,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    task = await _get_task_or_404(db_session, task_id, current_user)
    delete_artifact(task.code, path)
