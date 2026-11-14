"""
Подключение к Google Calendar (раздел 19.8 ТЗ): вход из профиля, выбор
календарей, ручная синхронизация, отключение и адрес возврата из Google.

Адрес возврата открывает браузер после входа у Google, поэтому токена сессии
трекера у запроса нет: пользователя определяет одноразовый `state`. Итог
входа — переход на страницу профиля с `?calendar=connected|error`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_google_calendar
from api.schemas import (
    GoogleCalendarConnectionResponse,
    GoogleCalendarInfoResponse,
    GoogleCalendarLoginResponse,
    GoogleCalendarSelectionRequest,
    GoogleCalendarSyncResponse,
)
from app_logging.config import get_logger
from clients.google_calendar import GoogleCalendarClient, GoogleCalendarInfo
from db.models.daily import GoogleCalendarConnection
from db.models.users import User
from db.session import get_session
from services.calendar_sync import SyncResult, complete_login, sync_user_calendar
from services.errors import AppError
from services.google_calendar import (
    disconnect,
    get_connection,
    list_account_calendars,
    set_synced_calendars,
    start_authorization,
)
from services.redis_connection import redis_connection

logger = get_logger("api.calendar")

router = APIRouter(tags=["google-calendar"])

CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
GoogleCalendar = Annotated[GoogleCalendarClient, Depends(get_google_calendar)]

PROFILE_PATH = "/profile"
_RESULT_PARAM = "calendar"
_CONNECTED = "connected"
_FAILED = "error"


def _profile_redirect(result: str) -> RedirectResponse:
    return RedirectResponse(f"{PROFILE_PATH}?{_RESULT_PARAM}={result}", status_code=303)


@router.get("/calendar/google/callback", include_in_schema=False)
async def google_calendar_callback(
    db_session: DbSession,
    google_calendar: GoogleCalendar,
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    """
    Отказ во входе у Google, устаревший `state` или сбой обмена кода — переход
    в профиль с ошибкой.
    """
    if error or not state or not code:
        logger.info("google_calendar_login_declined", reason=error or "missing_code")
        return _profile_redirect(_FAILED)
    async with redis_connection() as redis_client:
        try:
            await complete_login(
                db_session,
                redis_client,
                google_calendar,
                state=state,
                code=code,
                now=datetime.now(UTC),
            )
        except AppError as exc:
            logger.warning("google_calendar_login_failed", reason=exc.message)
            return _profile_redirect(_FAILED)
    return _profile_redirect(_CONNECTED)


@router.get("/profile/google-calendar", response_model=GoogleCalendarConnectionResponse | None)
async def read_google_calendar(
    db_session: DbSession,
    current_user: CurrentUser,
) -> GoogleCalendarConnection | None:
    """`null` — календарь не подключён."""
    return await get_connection(db_session, user_id=current_user.id)


@router.post("/profile/google-calendar/login", response_model=GoogleCalendarLoginResponse)
async def start_google_calendar_login(
    current_user: CurrentUser,
    google_calendar: GoogleCalendar,
) -> GoogleCalendarLoginResponse:
    async with redis_connection() as redis_client:
        url = await start_authorization(redis_client, google_calendar, user=current_user)
    return GoogleCalendarLoginResponse(url=url)


@router.get(
    "/profile/google-calendar/calendars",
    response_model=list[GoogleCalendarInfoResponse],
)
async def read_account_calendars(
    db_session: DbSession,
    current_user: CurrentUser,
    google_calendar: GoogleCalendar,
) -> list[GoogleCalendarInfo]:
    return await list_account_calendars(db_session, google_calendar, user=current_user)


@router.put("/profile/google-calendar/calendars", response_model=GoogleCalendarConnectionResponse)
async def update_synced_calendars(
    body: GoogleCalendarSelectionRequest,
    db_session: DbSession,
    current_user: CurrentUser,
) -> GoogleCalendarConnection:
    return await set_synced_calendars(
        db_session,
        user=current_user,
        calendar_ids=body.calendar_ids,
    )


@router.post("/profile/google-calendar/sync", response_model=GoogleCalendarSyncResponse)
async def sync_google_calendar(
    db_session: DbSession,
    current_user: CurrentUser,
    google_calendar: GoogleCalendar,
) -> SyncResult:
    async with redis_connection() as redis_client:
        return await sync_user_calendar(
            db_session,
            redis_client,
            google_calendar,
            user_id=current_user.id,
            now=datetime.now(UTC),
        )


@router.delete("/profile/google-calendar", status_code=204)
async def disconnect_google_calendar(
    db_session: DbSession,
    current_user: CurrentUser,
    google_calendar: GoogleCalendar,
) -> None:
    await disconnect(db_session, google_calendar, user=current_user)
