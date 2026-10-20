"""Административная часть — «Мониторинг» (раздел 13.4, 15.5, 17.2 ТЗ):
`app_logs` с фильтрами, сводка выполнения нод, активные Celery-задачи."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_admin
from api.schemas import ActiveCeleryTaskResponse, AppLogResponse, NodeRunResponse
from db.models.enums import AppLogLevel, NodeLogStatus, NodeLogTriggerType
from db.models.logs import AppLog
from db.models.users import User
from db.session import get_session
from services.monitoring import (
    InspectActiveResponse,
    NodeRunFilters,
    attach_task_codes,
    list_node_runs,
    parse_active_celery_tasks,
)
from tasks.celery_app import celery_app

router = APIRouter(prefix="/app-logs", tags=["admin-monitoring"])
monitoring_router = APIRouter(prefix="/monitoring", tags=["admin-monitoring"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000
# Сколько ждать ответа воркеров: не ответившие за это время в список не попадут.
_INSPECT_TIMEOUT_SECONDS = 1.0


@router.get("", response_model=list[AppLogResponse])
async def list_app_logs(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
    level: AppLogLevel | None = None,
    source: str | None = None,
    task_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[AppLog]:
    stmt = sa.select(AppLog).order_by(AppLog.created_at.desc()).limit(min(limit, _MAX_LIMIT))
    if level is not None:
        stmt = stmt.where(AppLog.level == level)
    if source is not None:
        stmt = stmt.where(AppLog.source == source)
    if task_id is not None:
        stmt = stmt.where(AppLog.task_id == task_id)
    if created_from is not None:
        stmt = stmt.where(AppLog.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(AppLog.created_at <= created_to)
    return list((await db_session.execute(stmt)).scalars().all())


@monitoring_router.get("/node-runs", response_model=list[NodeRunResponse])
async def list_node_runs_report(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
    task_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    status: NodeLogStatus | None = None,
    trigger_type: NodeLogTriggerType | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[NodeRunResponse]:
    """Раздел 13.4: сводная выборка по всем задачам поверх `node_logs`."""
    rows = await list_node_runs(
        db_session,
        filters=NodeRunFilters(
            task_id=task_id,
            node_id=node_id,
            status=status,
            trigger_type=trigger_type,
            started_from=started_from,
            started_to=started_to,
        ),
        limit=min(limit, _MAX_LIMIT),
    )
    return [NodeRunResponse.model_validate(row) for row in rows]


def _inspect_active() -> InspectActiveResponse | None:
    """Синхронный опрос воркеров через брокер — вызывается в отдельном потоке."""
    result: InspectActiveResponse | None = celery_app.control.inspect(
        timeout=_INSPECT_TIMEOUT_SECONDS,
    ).active()
    return result


@monitoring_router.get("/celery-tasks", response_model=list[ActiveCeleryTaskResponse])
async def list_active_celery_tasks(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[ActiveCeleryTaskResponse]:
    """Раздел 15.5: активные Celery-задачи по всем пользователям."""
    raw = await asyncio.to_thread(_inspect_active)
    tasks = await attach_task_codes(db_session, parse_active_celery_tasks(raw))
    return [ActiveCeleryTaskResponse.model_validate(task) for task in tasks]
