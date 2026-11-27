"""
FastAPI-зависимости: текущий пользователь, проверка роли (раздел 19.1, 19.2 ТЗ),
LLM-прокси и Google Calendar (раздел 19.8).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from clients.cliproxy import CliproxyManagementClient, open_cliproxy_client
from clients.google_calendar import GoogleCalendarClient
from db.models.enums import UserRole
from db.models.users import User
from db.session import get_session
from services.auth import load_session_user
from services.auth_tokens import InvalidSessionTokenError, verify_session_token
from services.browser_session import session_cookie_name
from services.errors import ForbiddenError, UnauthorizedError
from services.google_calendar import open_google_calendar_client


async def get_current_user(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    token = request.cookies.get(session_cookie_name())
    if not token:
        raise UnauthorizedError("Не передана cookie сессии")
    try:
        claims = verify_session_token(token)
    except InvalidSessionTokenError as exc:
        raise UnauthorizedError(str(exc)) from exc
    return await load_session_user(db_session, claims)


async def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if current_user.role is not UserRole.ADMIN:
        raise ForbiddenError("Требуется роль admin")
    return current_user


async def get_cliproxy() -> AsyncIterator[CliproxyManagementClient]:
    """Клиент management API LLM-прокси на время запроса (раздел 19.7)."""
    async with open_cliproxy_client() as client:
        yield client


async def get_google_calendar() -> AsyncIterator[GoogleCalendarClient]:
    """
    Клиент Google OAuth и Calendar API на время запроса (раздел 19.8).
    """
    async with open_google_calendar_client() as client:
        yield client
