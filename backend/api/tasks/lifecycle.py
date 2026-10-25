"""
Жизненный цикл задачи: пайплайн, запуск, перезапуск, возврат в новые,
очистка, пауза/продолжение/остановка, мост и отмена (раздел 13, 14 ТЗ).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import BindPipelineRequest, TaskResponse
from api.tasks.common import TASKS_PREFIX, TASKS_TAGS, get_task_or_404, require_status
from db.models.enums import TaskStatus
from db.models.tasks import Task
from db.models.users import User
from db.session import get_session
from services.access import get_pipeline_for_user
from services.errors import ConflictError, ValidationError
from services.integrity import ensure_pipeline_attachable
from services.redis_connection import redis_connection
from services.remote_control import start_bridge_reconnect
from services.session_context import clear_task_session_context
from services.task_cleanup import cleanup_task_repositories
from services.task_control import TaskControlCommand, request_task_control
from services.task_launch import ensure_task_launchable
from services.task_nodes import bind_pipeline_to_task
from services.task_status import reset_task_to_new, transition_task_status
from services.task_workspace import resolve_repos_root
from tasks.session_worker import run_task_session

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)


@router.post("/{task_id}/pipeline", response_model=TaskResponse)
async def bind_pipeline(
    task_id: uuid.UUID,
    body: BindPipelineRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 3.1, правило 10 CLAUDE.md: создание `task_nodes` и обновление
    `tasks.pipeline_id` — атомарно, в одной транзакции."""
    task = await get_task_or_404(db_session, task_id, current_user)
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
    task = await get_task_or_404(db_session, task_id, current_user)
    await ensure_task_launchable(db_session, task)
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
    task = await get_task_or_404(db_session, task_id, current_user)
    if task.status is not TaskStatus.FAILED or task.last_failed_order_index is None:
        raise ValidationError("Перезапуск доступен только для задачи в статусе failed")
    await ensure_task_launchable(db_session, task)
    run_task_session.delay(
        str(task_id),
        start_after_order_index=task.last_failed_order_index - 1,
    )
    await db_session.refresh(task)
    return task


@router.post("/{task_id}/reset", response_model=TaskResponse)
async def reset_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Task:
    """Раздел 14.2 «Вернуть в новые»: из `failed`/`done` — чтобы сменить пайплайн."""
    await get_task_or_404(db_session, task_id, current_user)
    updated = await reset_task_to_new(db_session, task_id=task_id)
    await db_session.refresh(updated)
    return updated


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
    task = await get_task_or_404(db_session, task_id, current_user)
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
    task = await get_task_or_404(db_session, task_id, current_user)
    await clear_task_session_context(db_session, task=task)
    await db_session.refresh(task)
    return task


async def _send_task_control(task_id: uuid.UUID, command: TaskControlCommand) -> None:
    async with redis_connection() as redis_client:
        await request_task_control(redis_client, task_id, command)


@router.post("/{task_id}/pause", status_code=202)
async def pause_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 14.2 «Приостановить»: текущая нода дорабатывает, следующая
    не начинается — статус `paused` выставит воркер, владеющий сессией."""
    task = await get_task_or_404(db_session, task_id, current_user)
    require_status(
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
    task = await get_task_or_404(db_session, task_id, current_user)
    require_status(task, frozenset({TaskStatus.PAUSED}), "Задача не на паузе")
    await _send_task_control(task_id, TaskControlCommand.RESUME)


@router.post("/{task_id}/stop", status_code=202)
async def stop_task(
    task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Раздел 14.2 «Остановить»: текущее обращение к сессии прерывается,
    задача переходит в `failed` и перезапускается штатной кнопкой."""
    task = await get_task_or_404(db_session, task_id, current_user)
    require_status(
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
    task = await get_task_or_404(db_session, task_id, current_user)
    async with redis_connection() as redis_client:
        await start_bridge_reconnect(db_session, task=task, redis_client=redis_client)


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
    await get_task_or_404(db_session, task_id, current_user)
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
