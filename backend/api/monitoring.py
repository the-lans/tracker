"""Административная часть — «Мониторинг» (раздел 15.5, 17.2 ТЗ): `app_logs`
с фильтрами."""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_admin
from api.schemas import AppLogResponse
from db.models.enums import AppLogLevel
from db.models.logs import AppLog
from db.models.users import User
from db.session import get_session

router = APIRouter(prefix="/app-logs", tags=["admin-monitoring"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000


@router.get("", response_model=list[AppLogResponse])
async def list_app_logs(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
    level: AppLogLevel | None = None,
    source: str | None = None,
    task_id: uuid.UUID | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[AppLog]:
    stmt = sa.select(AppLog).order_by(AppLog.created_at.desc()).limit(min(limit, _MAX_LIMIT))
    if level is not None:
        stmt = stmt.where(AppLog.level == level)
    if source is not None:
        stmt = stmt.where(AppLog.source == source)
    if task_id is not None:
        stmt = stmt.where(AppLog.task_id == task_id)
    return list((await db_session.execute(stmt)).scalars().all())
