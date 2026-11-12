"""Лента событий пользователя и администраторов (раздел 18.4 ТЗ)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import EventResponse
from db.models.enums import EventAudience, EventCategory, UserRole
from db.models.events import Event
from db.models.users import User
from db.session import get_session
from services.errors import ForbiddenError
from services.events import MAX_EVENTS_PAGE, EventFilters, list_events

router = APIRouter(prefix="/events", tags=["events"])

_DEFAULT_PAGE = 50


@router.get("", response_model=list[EventResponse])
async def list_events_endpoint(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    audience: EventAudience = EventAudience.USER,
    category: EventCategory | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_EVENTS_PAGE)] = _DEFAULT_PAGE,
) -> list[Event]:
    """«Мои» — события текущего пользователя, «Системные» — только администратору."""
    if audience is EventAudience.ADMINS and current_user.role is not UserRole.ADMIN:
        raise ForbiddenError("Системные события доступны только администратору")
    filters = EventFilters(
        audience=audience,
        user_id=current_user.id,
        category=category,
        before=before,
    )
    return list(await list_events(db_session, filters, limit=limit))
