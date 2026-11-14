"""
Подключение к Google Calendar (раздел 19.8 ТЗ): пользователь в профиле входит
в указанный Google-аккаунт, трекер получает доступ к его календарям только на
чтение и хранит refresh-токен зашифрованным (раздел 19.4). События календаря
приходят в «Дейли» синхронизацией (`services/calendar_sync.py`).

Вход — OAuth code flow тем же OAuth-клиентом, что и вход в трекер: ссылка
входа несёт одноразовый `state` (Redis, 10 минут), Google возвращает браузер
на `https://<DOMAIN>/api/calendar/google/callback`. Отозванный доступ
переводит подключение в «нужен повторный вход» — уведомление уходит один
раз, после compare-and-swap статуса (правило 12).
"""

from __future__ import annotations

import dataclasses
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from app_logging.config import get_logger
from clients.google_calendar import (
    CalendarAuthRevokedError,
    GoogleCalendarClient,
    GoogleCalendarInfo,
    GoogleOAuthConfig,
)
from db.models.daily import PRIMARY_CALENDAR_ID, GoogleCalendarConnection
from db.models.enums import GoogleCalendarStatus
from db.queries.daily import (
    delete_all_google_events,
    lock_calendar_connection,
    swap_calendar_status,
)
from services.crypto import decrypt, encrypt
from services.errors import ExternalServiceError, NotFoundError, ValidationError
from services.notifications import NotificationEvent, notify_user_event

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

logger = get_logger("google_calendar")

GOOGLE_TIMEOUT_SECONDS = 20
CALLBACK_PATH = "/api/calendar/google/callback"
STATE_TTL_SECONDS = 10 * 60
MAX_SYNCED_CALENDARS = 20
MAX_CALENDAR_ID_LENGTH = 255
_STATE_KEY = "calendar:oauth:{state}"
_STATE_BYTES = 32

_NOT_CONNECTED = "Google Calendar не подключён"
_STATE_EXPIRED = "Ссылка входа в Google устарела — подключите календарь заново"
_NO_REFRESH_TOKEN = (
    "Google не выдал постоянный доступ — отзовите доступ трекера в аккаунте Google и войдите снова"
)
_NO_EMAIL = "Google не сообщил адрес аккаунта"
_NO_CALENDARS = "Выберите хотя бы один календарь"
_TOO_MANY_CALENDARS = f"Можно выбрать не больше {MAX_SYNCED_CALENDARS} календарей"
_BAD_CALENDAR_ID = "Недопустимый идентификатор календаря"
_REAUTH_DETAIL = "Google отозвал доступ к календарю {email} — войдите заново в профиле"


@dataclass(frozen=True, slots=True)
class ConnectedAccount:
    user_id: uuid.UUID
    email: str


def google_oauth_config() -> GoogleOAuthConfig:
    """OAuth-клиент входа в трекер (раздел 19.1); адрес возврата — на домене трекера."""
    return GoogleOAuthConfig(
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        redirect_uri=f"https://{os.environ['DOMAIN']}{CALLBACK_PATH}",
    )


@asynccontextmanager
async def open_google_calendar_client() -> AsyncIterator[GoogleCalendarClient]:
    async with httpx.AsyncClient(timeout=GOOGLE_TIMEOUT_SECONDS) as http_client:
        yield GoogleCalendarClient(config=google_oauth_config(), http_client=http_client)


def _state_key(state: str) -> str:
    return _STATE_KEY.format(state=state)


async def get_connection(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> GoogleCalendarConnection | None:
    return await db_session.get(GoogleCalendarConnection, user_id)


async def require_connection(db_session: AsyncSession, *, user: User) -> GoogleCalendarConnection:
    connection = await get_connection(db_session, user_id=user.id)
    if connection is None:
        raise NotFoundError(_NOT_CONNECTED)
    return connection


async def start_authorization(
    redis_client: Redis,
    client: GoogleCalendarClient,
    *,
    user: User,
) -> str:
    state = secrets.token_urlsafe(_STATE_BYTES)
    await redis_client.set(_state_key(state), str(user.id), ex=STATE_TTL_SECONDS)
    logger.info("google_calendar_login_started")
    return client.authorization_url(state=state)


async def _account_email(
    client: GoogleCalendarClient,
    *,
    access_token: str,
    email: str | None,
) -> str:
    """Email из `id_token`, иначе — идентификатор основного календаря (это и есть адрес)."""
    if email:
        return email
    calendars = await client.list_calendars(access_token=access_token)
    primary = next((calendar.id for calendar in calendars if calendar.primary), None)
    if primary is None:
        raise ExternalServiceError(_NO_EMAIL, is_transient=False)
    return primary


async def complete_authorization(
    db_session: AsyncSession,
    redis_client: Redis,
    client: GoogleCalendarClient,
    *,
    state: str,
    code: str,
) -> ConnectedAccount:
    """
    Одноразовый `state` определяет пользователя: повтор той же ссылки или
    чужой `state` не подключает календарь. Другой аккаунт Google заменяет
    прежний — его события удаляются, выбор календарей сбрасывается.
    """
    raw_user_id = await redis_client.getdel(_state_key(state))
    if raw_user_id is None:
        raise ValidationError(_STATE_EXPIRED)
    user_id = uuid.UUID(raw_user_id.decode() if isinstance(raw_user_id, bytes) else raw_user_id)
    tokens = await client.exchange_code(code)
    if tokens.refresh_token is None:
        raise ExternalServiceError(_NO_REFRESH_TOKEN, is_transient=False)
    email = await _account_email(client, access_token=tokens.access_token, email=tokens.email)
    connection = await lock_calendar_connection(db_session, user_id=user_id)
    if connection is None:
        connection = GoogleCalendarConnection(user_id=user_id, google_email=email)
        db_session.add(connection)
    elif connection.google_email != email:
        await delete_all_google_events(db_session, user_id=user_id)
    if connection.google_email != email or not connection.calendar_ids:
        connection.calendar_ids = [PRIMARY_CALENDAR_ID]
    connection.google_email = email
    connection.refresh_token_encrypted = encrypt(tokens.refresh_token)
    connection.status = GoogleCalendarStatus.CONNECTED
    connection.last_error = None
    await db_session.commit()
    logger.info("google_calendar_connected", user_id=str(user_id))
    return ConnectedAccount(user_id=user_id, email=email)


async def mark_needs_reauth(
    db_session: AsyncSession,
    *,
    connection: GoogleCalendarConnection,
) -> None:
    """Compare-and-swap статуса: уведомление — только при первом переходе."""
    detail = _REAUTH_DETAIL.format(email=connection.google_email)
    changed = await swap_calendar_status(
        db_session,
        user_id=connection.user_id,
        expected=GoogleCalendarStatus.CONNECTED,
        status=GoogleCalendarStatus.NEEDS_REAUTH,
        last_error=detail,
    )
    await db_session.commit()
    await db_session.refresh(connection)
    if not changed:
        return
    logger.warning("google_calendar_reauth_required", user_id=str(connection.user_id))
    await notify_user_event(
        db_session,
        event=NotificationEvent.CALENDAR_LOGIN_REQUIRED,
        user_id=connection.user_id,
        detail=detail,
    )


async def access_token_for(
    db_session: AsyncSession,
    client: GoogleCalendarClient,
    *,
    connection: GoogleCalendarConnection,
) -> str | None:
    """Свежий access-токен; отозванный доступ — `None` и «нужен повторный вход»."""
    try:
        return await client.refresh_access_token(decrypt(connection.refresh_token_encrypted))
    except CalendarAuthRevokedError:
        await mark_needs_reauth(db_session, connection=connection)
        return None


async def list_account_calendars(
    db_session: AsyncSession,
    client: GoogleCalendarClient,
    *,
    user: User,
) -> list[GoogleCalendarInfo]:
    connection = await require_connection(db_session, user=user)
    access_token = await access_token_for(db_session, client, connection=connection)
    if access_token is None:
        return []
    calendars = await client.list_calendars(access_token=access_token)
    # Основной календарь хранится как `primary` (выбор по умолчанию), а Google
    # отдаёт его под адресом аккаунта — один и тот же календарь не должен
    # выбираться дважды под разными идентификаторами.
    return [
        dataclasses.replace(calendar, id=PRIMARY_CALENDAR_ID) if calendar.primary else calendar
        for calendar in calendars
    ]


def validate_calendar_ids(calendar_ids: list[str]) -> list[str]:
    unique = list(dict.fromkeys(calendar_id.strip() for calendar_id in calendar_ids))
    if not unique:
        raise ValidationError(_NO_CALENDARS)
    if len(unique) > MAX_SYNCED_CALENDARS:
        raise ValidationError(_TOO_MANY_CALENDARS)
    if any(not calendar_id or len(calendar_id) > MAX_CALENDAR_ID_LENGTH for calendar_id in unique):
        raise ValidationError(_BAD_CALENDAR_ID)
    return unique


async def set_synced_calendars(
    db_session: AsyncSession,
    *,
    user: User,
    calendar_ids: list[str],
) -> GoogleCalendarConnection:
    """Снятые календари исчезнут из «Дейли» при следующей синхронизации."""
    connection = await require_connection(db_session, user=user)
    connection.calendar_ids = validate_calendar_ids(calendar_ids)
    await db_session.commit()
    logger.info("google_calendars_selected", count=len(connection.calendar_ids))
    return connection


async def disconnect(
    db_session: AsyncSession,
    client: GoogleCalendarClient,
    *,
    user: User,
) -> None:
    """
    Отключение удаляет подключение и события календаря; отзыв доступа у
    Google — по возможности: без него токен в трекере всё равно удалён.
    """
    connection = await require_connection(db_session, user=user)
    try:
        await client.revoke(decrypt(connection.refresh_token_encrypted))
    except ExternalServiceError as exc:
        logger.warning("google_calendar_revoke_failed", reason=exc.message)
    # Блокировка после запроса к Google: идущая синхронизация успеет записать
    # события, и они удалятся вместе с подключением.
    locked = await lock_calendar_connection(db_session, user_id=user.id)
    if locked is not None:
        await delete_all_google_events(db_session, user_id=user.id)
        await db_session.delete(locked)
    await db_session.commit()
    logger.info("google_calendar_disconnected")
