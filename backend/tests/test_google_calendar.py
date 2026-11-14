"""
Google Calendar в «Дейли» (раздел 19.8 ТЗ): клиент API, вход по одноразовому
`state`, синхронизация событий, отзыв доступа и API профиля.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import pytest
import sqlalchemy as sa

from api.dependencies import get_google_calendar
from clients.google_calendar import CalendarAuthRevokedError
from db.models.daily import DailyEvent, GoogleCalendarConnection
from db.models.enums import DailyEventSource, GoogleCalendarStatus
from db.models.events import Event
from main import app
from services import calendar_sync
from services.calendar_sync import sync_all_calendars, sync_user_calendar
from services.crypto import decrypt
from services.errors import ConflictError, ExternalServiceError, ValidationError
from services.google_calendar import (
    complete_authorization,
    disconnect,
    set_synced_calendars,
    start_authorization,
)
from tests.factories import make_user
from tests.google_calendar_support import (
    ACCESS_TOKEN,
    GOOGLE_EMAIL,
    REFRESH_TOKEN,
    FakeGoogle,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 16)


def _timed(event_id: str, start: str, end: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": "Созвон",
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        **fields,
    }


def _all_day(event_id: str, start: str, end: str) -> dict[str, Any]:
    return {"id": event_id, "summary": "Отпуск", "start": {"date": start}, "end": {"date": end}}


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    return await make_user(db_session)


async def _connect(
    db_session: AsyncSession, redis_client: Redis, google: FakeGoogle, user: User
) -> None:
    url = await start_authorization(redis_client, google.client(), user=user)
    state = parse_qs(urlsplit(url).query)["state"][0]
    await complete_authorization(
        db_session, redis_client, google.client(), state=state, code="code"
    )


async def _google_events(db_session: AsyncSession, user: User) -> list[DailyEvent]:
    rows = await db_session.execute(
        sa.select(DailyEvent)
        .where(DailyEvent.user_id == user.id, DailyEvent.source == DailyEventSource.GOOGLE)
        .order_by(DailyEvent.external_id),
    )
    return list(rows.scalars())


class TestClient:
    async def test_events_paged_and_cancelled_skipped(self, google: FakeGoogle) -> None:
        google.events["primary"] = [
            [_timed("a", "2026-11-16T10:00:00+03:00", "2026-11-16T11:00:00+03:00")],
            [
                _timed("b", "2026-11-16T12:00:00+03:00", "2026-11-16T13:00:00+03:00"),
                _timed(
                    "c",
                    "2026-11-16T14:00:00+03:00",
                    "2026-11-16T15:00:00+03:00",
                    status="cancelled",
                ),
            ],
        ]

        events = await google.client().list_events(
            access_token=ACCESS_TOKEN,
            calendar_id="primary",
            time_min=NOW,
            time_max=NOW,
        )

        assert [event.id for event in events] == ["a", "b"]
        assert google.requests[-1].headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"

    async def test_revoked_refresh(self, google: FakeGoogle) -> None:
        google.revoked = True

        with pytest.raises(CalendarAuthRevokedError):
            await google.client().refresh_access_token(REFRESH_TOKEN)

    async def test_rejected_code(self, google: FakeGoogle) -> None:
        """`invalid_grant` на обмене кода — сбой входа, а не «нужен повторный вход»."""
        google.reject_code = True

        with pytest.raises(ExternalServiceError, match="код входа"):
            await google.client().exchange_code("expired")

    def test_authorization_url_offline_readonly(self, google: FakeGoogle) -> None:
        query = parse_qs(urlsplit(google.client().authorization_url(state="s")).query)

        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]
        assert "https://www.googleapis.com/auth/calendar.readonly" in query["scope"][0]


class TestAuthorization:
    async def test_connects_with_encrypted_token(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        user: User,
    ) -> None:
        await _connect(db_session, redis_client, google, user)

        connection = await db_session.get(GoogleCalendarConnection, user.id)
        assert connection is not None
        assert (connection.google_email, connection.calendar_ids) == (GOOGLE_EMAIL, ["primary"])
        assert connection.refresh_token_encrypted != REFRESH_TOKEN
        assert decrypt(connection.refresh_token_encrypted) == REFRESH_TOKEN

    async def test_state_is_single_use(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        user: User,
    ) -> None:
        url = await start_authorization(redis_client, google.client(), user=user)
        state = parse_qs(urlsplit(url).query)["state"][0]
        await complete_authorization(
            db_session, redis_client, google.client(), state=state, code="c"
        )

        with pytest.raises(ValidationError):
            await complete_authorization(
                db_session, redis_client, google.client(), state=state, code="c"
            )
        with pytest.raises(ValidationError):
            await complete_authorization(
                db_session, redis_client, google.client(), state="forged", code="c"
            )

    async def test_other_account_drops_events(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        user: User,
    ) -> None:
        await _connect(db_session, redis_client, google, user)
        await set_synced_calendars(db_session, user=user, calendar_ids=["work@example.com"])
        db_session.add(
            DailyEvent(
                user_id=user.id,
                source=DailyEventSource.GOOGLE,
                day=TODAY,
                end_day=TODAY,
                title="Старое",
                hidden=False,
                calendar_id="work@example.com",
                external_id="old",
            ),
        )
        await db_session.flush()
        google.email = "other@example.com"

        await _connect(db_session, redis_client, google, user)

        connection = await db_session.get(GoogleCalendarConnection, user.id)
        assert connection is not None
        assert (connection.google_email, connection.calendar_ids) == (
            "other@example.com",
            ["primary"],
        )
        assert await _google_events(db_session, user) == []

    @pytest.mark.parametrize(
        "calendar_ids",
        [[], [""], [f"c{index}" for index in range(21)]],
        ids=["пусто", "пустой-id", "слишком-много"],
    )
    async def test_calendar_selection_validated(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        user: User,
        calendar_ids: list[str],
    ) -> None:
        await _connect(db_session, redis_client, google, user)

        with pytest.raises(ValidationError):
            await set_synced_calendars(db_session, user=user, calendar_ids=calendar_ids)

    async def test_disconnect_revokes_and_removes(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        user: User,
    ) -> None:
        await _connect(db_session, redis_client, google, user)
        google.events["primary"] = [
            [_timed("a", "2026-11-16T10:00:00+03:00", "2026-11-16T11:00:00+03:00")]
        ]
        await sync_user_calendar(
            db_session, redis_client, google.client(), user_id=user.id, now=NOW
        )

        await disconnect(db_session, google.client(), user=user)

        assert await db_session.get(GoogleCalendarConnection, user.id) is None
        assert await _google_events(db_session, user) == []
        assert str(google.requests[-1].url).endswith("/revoke")


class TestSync:
    @pytest.fixture
    async def connected(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        user: User,
    ) -> User:
        await _connect(db_session, redis_client, google, user)
        return user

    async def test_days_of_events(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        connected: User,
    ) -> None:
        google.events["primary"] = [
            [
                # 07:30 МСК — ещё вчерашний день при начале дня 08:00.
                _timed("early", "2026-11-16T07:30:00+03:00", "2026-11-16T07:50:00+03:00"),
                # Кончается ровно в начале следующего дня — следующий день не занимает.
                _timed("evening", "2026-11-16T20:00:00+03:00", "2026-11-17T08:00:00+03:00"),
                _all_day("vacation", "2026-11-16", "2026-11-18"),
            ],
        ]

        result = await sync_user_calendar(
            db_session,
            redis_client,
            google.client(),
            user_id=connected.id,
            now=NOW,
        )

        assert result.synced is True
        assert {
            (event.external_id, event.day, event.end_day)
            for event in await _google_events(db_session, connected)
        } == {
            ("early", date(2026, 11, 15), date(2026, 11, 15)),
            ("evening", TODAY, TODAY),
            ("vacation", TODAY, date(2026, 11, 17)),
        }
        params = google.requests[-1].url.params
        # Окно — с начала дня 7 дней назад до конца завтрашнего дня.
        assert (params["timeMin"], params["timeMax"]) == (
            "2026-11-09T05:00:00+00:00",
            "2026-11-18T05:00:00+00:00",
        )

    async def test_resync_keeps_hidden_and_drops_missing(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        connected: User,
    ) -> None:
        google.events["primary"] = [
            [
                _timed("kept", "2026-11-16T10:00:00+03:00", "2026-11-16T11:00:00+03:00"),
                _timed("gone", "2026-11-16T12:00:00+03:00", "2026-11-16T13:00:00+03:00"),
            ],
        ]
        await sync_user_calendar(
            db_session, redis_client, google.client(), user_id=connected.id, now=NOW
        )
        kept = next(
            event
            for event in await _google_events(db_session, connected)
            if event.external_id == "kept"
        )
        kept.hidden = True
        await db_session.commit()
        google.events["primary"] = [
            [
                _timed(
                    "kept",
                    "2026-11-16T10:00:00+03:00",
                    "2026-11-16T11:30:00+03:00",
                    summary="Перенесли",
                )
            ],
        ]

        await sync_user_calendar(
            db_session, redis_client, google.client(), user_id=connected.id, now=NOW
        )

        (event,) = await _google_events(db_session, connected)
        await db_session.refresh(event)
        assert (event.external_id, event.title, event.hidden) == ("kept", "Перенесли", True)

    async def test_missing_calendar_skipped(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        connected: User,
    ) -> None:
        """Удалённый в Google календарь не останавливает синхронизацию остальных."""
        await set_synced_calendars(db_session, user=connected, calendar_ids=["primary", "gone"])
        google.missing = {"gone"}
        google.events["primary"] = [
            [_timed("kept", "2026-11-16T10:00:00+03:00", "2026-11-16T11:00:00+03:00")],
        ]

        result = await sync_user_calendar(
            db_session, redis_client, google.client(), user_id=connected.id, now=NOW
        )

        connection = await db_session.get(GoogleCalendarConnection, connected.id)
        assert result.synced is True
        assert [event.external_id for event in await _google_events(db_session, connected)] == [
            "kept"
        ]
        assert connection is not None
        assert connection.last_error is not None
        assert "gone" in connection.last_error

    async def test_outdated_after_disconnect(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        connected: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Отключили, пока шёл запрос к Google, — события запроса не записываются."""
        google.events["primary"] = [
            [_timed("late", "2026-11-16T10:00:00+03:00", "2026-11-16T11:00:00+03:00")],
        ]

        async def disconnected(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(calendar_sync, "lock_calendar_connection", disconnected)
        user_id = connected.id

        result = await sync_user_calendar(
            db_session, redis_client, google.client(), user_id=user_id, now=NOW
        )

        events = await db_session.scalars(
            sa.select(DailyEvent.external_id).where(DailyEvent.user_id == user_id),
        )
        assert result.synced is False
        assert list(events) == []

    async def test_revoked_marks_once_and_notifies(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        connected: User,
    ) -> None:
        google.revoked = True

        first = await sync_user_calendar(
            db_session, redis_client, google.client(), user_id=connected.id, now=NOW
        )
        connection = await db_session.get(GoogleCalendarConnection, connected.id)
        assert connection is not None
        assert connection.status is GoogleCalendarStatus.NEEDS_REAUTH
        second = await sync_all_calendars(db_session, redis_client, google.client(), now=NOW)

        assert (first.synced, second) == (False, 0)
        notices = await db_session.scalar(
            sa.select(sa.func.count())
            .select_from(Event)
            .where(Event.user_id == connected.id, Event.event_type == "calendar_login_required"),
        )
        assert notices == 1

    async def test_busy_sync(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        connected: User,
    ) -> None:
        await redis_client.set(f"lock:calendar:sync:{connected.id}", "other", ex=60)

        with pytest.raises(ConflictError):
            await sync_user_calendar(
                db_session, redis_client, google.client(), user_id=connected.id, now=NOW
            )

    async def test_selected_calendars(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        google: FakeGoogle,
        connected: User,
    ) -> None:
        google.events["work@example.com"] = [
            [_timed("w", "2026-11-16T10:00:00+03:00", "2026-11-16T11:00:00+03:00")],
        ]
        await set_synced_calendars(db_session, user=connected, calendar_ids=["work@example.com"])

        await sync_user_calendar(
            db_session, redis_client, google.client(), user_id=connected.id, now=NOW
        )

        assert [
            (event.calendar_id, event.external_id)
            for event in await _google_events(db_session, connected)
        ] == [
            ("work@example.com", "w"),
        ]


class TestCalendarApi:
    @pytest.fixture
    def api_google(self, google: FakeGoogle) -> Iterator[FakeGoogle]:
        async def _client() -> AsyncIterator[Any]:
            yield google.client()

        app.dependency_overrides[get_google_calendar] = _client
        try:
            yield google
        finally:
            app.dependency_overrides.pop(get_google_calendar, None)

    async def test_login_callback_and_profile(
        self,
        authed_client: AsyncClient,
        api_google: FakeGoogle,
        redis_client: Redis,
    ) -> None:
        assert (await authed_client.get("/profile/google-calendar")).json() is None
        url = (await authed_client.post("/profile/google-calendar/login")).json()["url"]
        state = parse_qs(urlsplit(url).query)["state"][0]

        callback = await authed_client.get(
            "/calendar/google/callback",
            params={"state": state, "code": "code"},
        )
        profile = await authed_client.get("/profile/google-calendar")
        calendars = await authed_client.get("/profile/google-calendar/calendars")
        synced = await authed_client.post("/profile/google-calendar/sync")

        assert (callback.status_code, callback.headers["location"]) == (
            303,
            "/profile?calendar=connected",
        )
        assert profile.json()["google_email"] == GOOGLE_EMAIL
        assert REFRESH_TOKEN not in profile.text
        assert calendars.json() == [{"id": "primary", "summary": "Основной", "primary": True}]
        assert synced.json() == {"synced": True, "events": 0}
        assert (await authed_client.delete("/profile/google-calendar")).status_code == 204

    @pytest.mark.parametrize(
        "params",
        [{"error": "access_denied"}, {"state": "forged", "code": "code"}],
        ids=["отказ", "чужой-state"],
    )
    async def test_callback_failure(
        self,
        authed_client: AsyncClient,
        api_google: FakeGoogle,
        params: dict[str, str],
    ) -> None:
        response = await authed_client.get("/calendar/google/callback", params=params)

        assert (response.status_code, response.headers["location"]) == (
            303,
            "/profile?calendar=error",
        )

    async def test_callback_rejected_code(
        self,
        authed_client: AsyncClient,
        api_google: FakeGoogle,
    ) -> None:
        """Google не принял код входа — переход в профиль с ошибкой, а не 500."""
        api_google.reject_code = True
        url = (await authed_client.post("/profile/google-calendar/login")).json()["url"]
        state = parse_qs(urlsplit(url).query)["state"][0]

        response = await authed_client.get(
            "/calendar/google/callback",
            params={"state": state, "code": "expired"},
        )

        assert (response.status_code, response.headers["location"]) == (
            303,
            "/profile?calendar=error",
        )
        assert (await authed_client.get("/profile/google-calendar")).json() is None

    async def test_not_connected(self, authed_client: AsyncClient, api_google: FakeGoogle) -> None:
        assert (await authed_client.get("/profile/google-calendar/calendars")).status_code == 404

    async def test_revoked_calendar_list(
        self,
        authed_client: AsyncClient,
        api_google: FakeGoogle,
    ) -> None:
        """Отозванный доступ — 409 с причиной, а не пустой список календарей."""
        url = (await authed_client.post("/profile/google-calendar/login")).json()["url"]
        state = parse_qs(urlsplit(url).query)["state"][0]
        await authed_client.get(
            "/calendar/google/callback", params={"state": state, "code": "code"}
        )
        api_google.revoked = True

        calendars = await authed_client.get("/profile/google-calendar/calendars")
        profile = await authed_client.get("/profile/google-calendar")

        assert calendars.status_code == 409
        assert GOOGLE_EMAIL in calendars.json()["error"]["message"]
        assert profile.json()["status"] == "needs_reauth"
