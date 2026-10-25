"""Административная часть — «Периодические задачи» (раздел 15.5, 16.1 ТЗ).

Редактирование расписания не требует перезапуска процессов: `tasks/
periodic_scheduler.py::DatabaseScheduler` перечитывает `periodic_tasks` из
БД каждые ~10с — эндпоинт ниже лишь пишет строку, подхват уже реализован
на стороне Celery Beat.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_admin
from api.schemas import PeriodicTaskResponse, PeriodicTaskUpdateRequest
from db.models.periodic import PeriodicTask
from db.models.users import User
from db.session import get_session
from services.access import get_or_404
from services.periodic_tasks import update_periodic_task as update_periodic_task_settings
from tasks.celery_app import celery_app

router = APIRouter(prefix="/periodic-tasks", tags=["admin-periodic-tasks"])


async def _get_periodic_task_or_404(
    db_session: AsyncSession,
    periodic_task_id: uuid.UUID,
) -> PeriodicTask:
    return await get_or_404(
        db_session,
        PeriodicTask,
        periodic_task_id,
        not_found=f"Периодическая задача {periodic_task_id} не найдена",
    )


@router.get("", response_model=list[PeriodicTaskResponse])
async def list_periodic_tasks(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[PeriodicTask]:
    stmt = sa.select(PeriodicTask).order_by(PeriodicTask.display_name)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{periodic_task_id}", response_model=PeriodicTaskResponse)
async def get_periodic_task(
    periodic_task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> PeriodicTask:
    return await _get_periodic_task_or_404(db_session, periodic_task_id)


@router.patch("/{periodic_task_id}", response_model=PeriodicTaskResponse)
async def update_periodic_task(
    periodic_task_id: uuid.UUID,
    body: PeriodicTaskUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> PeriodicTask:
    periodic_task = await _get_periodic_task_or_404(db_session, periodic_task_id)
    return await update_periodic_task_settings(
        db_session,
        periodic_task=periodic_task,
        interval_seconds=body.interval_seconds,
        crontab_expression=body.crontab_expression,
        is_enabled=body.is_enabled,
        updated_by=admin.id,
    )


@router.post("/{periodic_task_id}/run-now", status_code=202)
async def run_periodic_task_now(
    periodic_task_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    """Раздел 15.5: «Запустить сейчас» — вне расписания.

    `periodic_task.name` — зарегистрированное Celery-имя задачи (см.
    `@celery_app.task(name=...)` в `tasks/periodic.py`), а не `task_path`
    (тот — человекочитаемый dotted-путь для отображения в админке)."""
    periodic_task = await _get_periodic_task_or_404(db_session, periodic_task_id)
    celery_app.send_task(periodic_task.name)
