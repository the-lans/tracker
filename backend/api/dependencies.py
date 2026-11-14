"""
FastAPI-зависимости: текущий пользователь, проверка роли (раздел 19.1, 19.2 ТЗ),
LLM-прокси и Google Calendar (раздел 19.8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from clients.cliproxy import CliproxyManagementClient, open_cliproxy_client
from clients.google_calendar import GoogleCalendarClient
from db.models.enums import UserRole
from db.models.users import User
from db.session import get_session
from services.auth_tokens import InvalidSessionTokenError, verify_session_token
from services.errors import ForbiddenError, UnauthorizedError
from services.google_calendar import open_google_calendar_client

_BEARER_PREFIX = "Bearer "


async def get_current_user(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise UnauthorizedError("Не передан токен сессии")
    token = authorization.removeprefix(_BEARER_PREFIX)
    try:
        user_id = verify_session_token(token)
    except InvalidSessionTokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    user = await db_session.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Пользователь не найден или заблокирован")
    return user


async def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role is not UserRole.ADMIN:
        raise ForbiddenError("Требуется роль admin")
    return current_user


async def get_cliproxy() -> AsyncIterator[CliproxyManagementClient]:
    """Клиент management API LLM-прокси на время запроса (раздел 19.7)."""
    async with open_cliproxy_client() as client:
        yield client


async def get_google_calendar() -> AsyncIterator[GoogleCalendarClient]:
    """Клиент Google OAuth и Calendar API на время запроса (раздел 19.8)."""
    async with open_google_calendar_client() as client:
        yield client
