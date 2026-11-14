"""Отметка задачи на сегодня или на завтра (раздел 15.8 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from db.models.users import User
from db.session import get_session
from services.day_marks import clear_day_mark, set_day_mark

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.put("/{task_id}/day-marks/{day}", status_code=204)
async def mark_task_day(
    task_id: uuid.UUID,
    day: date,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await set_day_mark(
        db_session,
        user=current_user,
        task_id=task_id,
        day=day,
        now=datetime.now(UTC),
    )


@router.delete("/{task_id}/day-marks/{day}", status_code=204)
async def unmark_task_day(
    task_id: uuid.UUID,
    day: date,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await clear_day_mark(
        db_session,
        user=current_user,
        task_id=task_id,
        day=day,
        now=datetime.now(UTC),
    )
