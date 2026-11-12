"""Лента событий — раздел 18.4 ТЗ: запись из уведомлений, итоги периодических задач, API."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import (
    EventAudience,
    EventCategory,
    PeriodicRunStatus,
    PeriodicScheduleType,
    UserRole,
)
from db.models.events import Event
from db.models.periodic import PeriodicTask
from db.models.tasks import Task
from db.models.users import User
from services import notifications
from services.events import EventDraft, purge_old_events, record_event
from services.notifications import (
    EVENT_CATEGORIES,
    NotificationEvent,
    notify_admins,
    notify_task_event,
    notify_user_event,
)
from services.periodic_tasks import outcome_event
from services.push_notifications import PushMessage
from tasks import periodic
from tasks.celery_app import BACKUP_TO_S3
from tests.factories import make_user

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.fixture
def pushed(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, str]]:
    sent: list[tuple[uuid.UUID, str]] = []

    async def record(_session: object, *, user_id: uuid.UUID, message: PushMessage) -> None:
        sent.append((user_id, message.title))

    monkeypatch.setattr(notifications, "send_push_to_user", record)
    return sent


async def _events(db_session: AsyncSession) -> list[Event]:
    return list((await db_session.scalars(sa.select(Event).order_by(Event.created_at))).all())


async def _task(db_session: AsyncSession, owner: User) -> Task:
    task = Task(code=f"RR-{uuid.uuid4().hex[:6]}", title="t", description="d", created_by=owner.id)
    db_session.add(task)
    await db_session.flush()
    return task


class TestCategories:
    def test_every_event_has_category(self) -> None:
        assert set(EVENT_CATEGORIES) == set(NotificationEvent)


class TestRecordedWithPush:
    async def test_task_event(
        self,
        db_session: AsyncSession,
        pushed: list[tuple[uuid.UUID, str]],
    ) -> None:
        owner = await make_user(db_session)
        task = await _task(db_session, owner)

        await notify_task_event(db_session, event=NotificationEvent.DONE, task=task)

        [event] = await _events(db_session)
        assert (event.audience, event.user_id, event.category, event.task_id) == (
            EventAudience.USER,
            owner.id,
            EventCategory.TASK,
            task.id,
        )
        assert (event.event_type, event.body) == ("done", f"{task.code}: t")
        assert pushed == [(owner.id, event.title)]

    @pytest.mark.usefixtures("redis_client")
    async def test_suppressed_series_gives_one_event(
        self,
        db_session: AsyncSession,
        pushed: list[tuple[uuid.UUID, str]],
    ) -> None:
        task = await _task(db_session, await make_user(db_session))

        for _ in range(2):
            await notify_task_event(
                db_session, event=NotificationEvent.AWAITING_DECISION, task=task
            )

        assert (len(await _events(db_session)), len(pushed)) == (1, 1)

    async def test_user_event(
        self,
        db_session: AsyncSession,
        pushed: list[tuple[uuid.UUID, str]],
    ) -> None:
        user = await make_user(db_session)

        await notify_user_event(
            db_session,
            event=NotificationEvent.LLM_LOGIN_REQUIRED,
            user_id=user.id,
            detail="Аккаунт «Основной»",
        )

        [event] = await _events(db_session)
        assert (event.category, event.user_id, event.task_id) == (
            EventCategory.LLM_ACCOUNT,
            user.id,
            None,
        )


class TestNotifyAdmins:
    @pytest.mark.parametrize(
        ("event", "pushes"),
        [
            (NotificationEvent.BACKUP_FAILED, True),
            (NotificationEvent.PERIODIC_TASK_FAILED, True),
            (NotificationEvent.BACKUP_SUCCEEDED, False),
            (NotificationEvent.BACKUP_VERIFIED, False),
            (NotificationEvent.PERIODIC_TASK_RECOVERED, False),
        ],
    )
    async def test_one_record_push_to_active_admins(
        self,
        db_session: AsyncSession,
        pushed: list[tuple[uuid.UUID, str]],
        event: NotificationEvent,
        pushes: bool,
    ) -> None:
        admins = [await make_user(db_session, role=UserRole.ADMIN) for _ in range(2)]
        blocked = await make_user(db_session, role=UserRole.ADMIN)
        blocked.is_active = False
        await make_user(db_session)

        await notify_admins(db_session, event=event, detail="подробности")

        [recorded] = await _events(db_session)
        assert (recorded.audience, recorded.user_id) == (EventAudience.ADMINS, None)
        expected = {admin.id for admin in admins} if pushes else set()
        assert {user_id for user_id, _ in pushed} == expected


class TestPeriodicOutcome:
    @pytest.mark.parametrize(
        ("previous", "current", "expected"),
        [
            (None, PeriodicRunStatus.FAILED, NotificationEvent.PERIODIC_TASK_FAILED),
            (
                PeriodicRunStatus.SUCCESS,
                PeriodicRunStatus.FAILED,
                NotificationEvent.PERIODIC_TASK_FAILED,
            ),
            (
                PeriodicRunStatus.RUNNING,
                PeriodicRunStatus.FAILED,
                NotificationEvent.PERIODIC_TASK_FAILED,
            ),
            (PeriodicRunStatus.FAILED, PeriodicRunStatus.FAILED, None),
            (
                PeriodicRunStatus.FAILED,
                PeriodicRunStatus.SUCCESS,
                NotificationEvent.PERIODIC_TASK_RECOVERED,
            ),
            (PeriodicRunStatus.SUCCESS, PeriodicRunStatus.SUCCESS, None),
            (None, PeriodicRunStatus.SUCCESS, None),
        ],
    )
    def test_only_on_change(
        self,
        previous: PeriodicRunStatus | None,
        current: PeriodicRunStatus,
        expected: NotificationEvent | None,
    ) -> None:
        assert outcome_event(previous, current) is expected

    @pytest.fixture
    def same_session(self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
        @asynccontextmanager
        async def factory() -> AsyncIterator[AsyncSession]:
            yield db_session

        monkeypatch.setattr(periodic, "async_session_factory", factory)

    async def _run(
        self,
        db_session: AsyncSession,
        *,
        name: str,
        previous: PeriodicRunStatus | None,
        body: Callable[[AsyncSession], Awaitable[None]],
    ) -> list[Event]:
        db_session.add(
            PeriodicTask(
                name=name,
                display_name=name,
                description="d",
                task_path=f"tasks.periodic.{name}",
                schedule_type=PeriodicScheduleType.INTERVAL,
                interval_seconds=60,
                last_run_status=previous,
            ),
        )
        await db_session.flush()
        await periodic._run_periodic_async(name, body)
        return await _events(db_session)

    @staticmethod
    async def _fails(_session: AsyncSession) -> None:
        raise RuntimeError("нет связи")

    @staticmethod
    async def _succeeds(_session: AsyncSession) -> None:
        return None

    @pytest.mark.usefixtures("same_session", "pushed")
    async def test_failure_after_success(self, db_session: AsyncSession) -> None:
        [event] = await self._run(
            db_session,
            name="check_example",
            previous=PeriodicRunStatus.SUCCESS,
            body=self._fails,
        )

        assert (event.event_type, event.body) == (
            "periodic_task_failed",
            "check_example: нет связи",
        )

    @pytest.mark.usefixtures("same_session", "pushed")
    async def test_recovery(self, db_session: AsyncSession) -> None:
        [event] = await self._run(
            db_session,
            name="check_example",
            previous=PeriodicRunStatus.FAILED,
            body=self._succeeds,
        )

        assert event.event_type == "periodic_task_recovered"

    @pytest.mark.usefixtures("same_session", "pushed")
    async def test_backup_reports_itself(self, db_session: AsyncSession) -> None:
        events = await self._run(
            db_session,
            name=BACKUP_TO_S3,
            previous=PeriodicRunStatus.SUCCESS,
            body=self._fails,
        )

        assert events == []


class TestPurge:
    async def test_removes_only_old(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        now = datetime.now(UTC)
        draft = EventDraft(category=EventCategory.TASK, event_type="done", title="t", body="b")
        await record_event(db_session, draft, user_id=user.id)
        await record_event(db_session, draft, user_id=user.id)
        [old, _fresh] = await _events(db_session)
        old.created_at = now - timedelta(days=91)
        await db_session.flush()

        deleted = await purge_old_events(db_session, now=now, threshold_days=90)

        assert deleted == 1
        assert [event.id for event in await _events(db_session)] == [_fresh.id]


class TestEventsApi:
    async def _record(
        self,
        db_session: AsyncSession,
        *,
        user_id: uuid.UUID | None,
        category: EventCategory = EventCategory.TASK,
        created_at: datetime | None = None,
    ) -> Event:
        event = Event(
            audience=EventAudience.ADMINS if user_id is None else EventAudience.USER,
            user_id=user_id,
            category=category,
            event_type="done",
            title="t",
            body="b",
            created_at=created_at or datetime.now(UTC),
        )
        db_session.add(event)
        await db_session.flush()
        return event

    async def test_own_events_only(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        own = await self._record(db_session, user_id=current_user.id)
        await self._record(db_session, user_id=(await make_user(db_session)).id)
        await self._record(db_session, user_id=None)

        response = await authed_client.get("/events")

        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(own.id)]

    async def test_admin_events_forbidden_for_user(self, authed_client: AsyncClient) -> None:
        response = await authed_client.get("/events", params={"audience": "admins"})

        assert response.status_code == 403

    async def test_admin_events(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
    ) -> None:
        system = await self._record(db_session, user_id=None)
        await self._record(db_session, user_id=admin_user.id)

        response = await admin_client.get("/events", params={"audience": "admins"})

        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(system.id)]

    async def test_category_and_pages(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        start = datetime.now(UTC)
        newest, middle, oldest = [
            await self._record(
                db_session,
                user_id=current_user.id,
                category=EventCategory.BACKUP,
                created_at=start - timedelta(minutes=minutes),
            )
            for minutes in (1, 2, 3)
        ]
        await self._record(db_session, user_id=current_user.id, category=EventCategory.TASK)

        first = await authed_client.get("/events", params={"category": "backup", "limit": 2})
        second = await authed_client.get(
            "/events",
            params={"category": "backup", "before": first.json()[-1]["created_at"]},
        )

        assert [item["id"] for item in first.json()] == [str(newest.id), str(middle.id)]
        assert [item["id"] for item in second.json()] == [str(oldest.id)]
