"""
«Дейли» (раздел 15.8 ТЗ): отметки задач, факт работы за день, прошлый день,
события и планы по шаблону.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest

from db.models.daily import DailyEvent
from db.models.enums import DailyEventSource, NodeLogStatus, NodeLogTriggerType, TaskStatus
from db.models.logs import NodeLog
from services.daily_clock import DailyClock, load_daily_clock
from services.daily_events import (
    ManualEventValues,
    create_manual_event,
    delete_manual_event,
    set_event_hidden,
    update_manual_event,
)
from services.daily_history import DayFact, day_view, previous_day
from services.daily_plans import (
    DEFAULT_DAILY_TEMPLATE,
    create_daily_plan,
    get_daily_template,
    preview_daily_template,
    regenerate_daily_plan,
    reset_daily_template,
    save_daily_template,
    validate_daily_template,
)
from services.day_marks import clear_day_mark, recent_day_marks, set_day_mark
from services.errors import ConflictError, NotFoundError, ValidationError
from services.tracker_day import DayWindow
from tests.factories import make_task, make_user

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task
    from db.models.users import User

# 12:00 МСК: сегодня — 16.11 при начале дня 08:00.
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 16)
TOMORROW = date(2026, 11, 17)
YESTERDAY = date(2026, 11, 15)
CLOCK = DailyClock(window=DayWindow(today=TODAY), day_start=time(8, 0))
# 08:00 МСК 15.11 и 16.11 — границы вчерашнего дня.
YESTERDAY_START = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)
TODAY_START = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    return await make_user(db_session)


async def _task(db_session: AsyncSession, user: User, title: str = "t", **fields: object) -> Task:
    return await make_task(db_session, created_by=user.id, title=title, **fields)


async def _mark(db_session: AsyncSession, user: User, task: Task, day: date) -> None:
    """Отметка прошлого дня напрямую: API ставит только сегодня и завтра."""
    from db.queries.daily import insert_mark

    await insert_mark(db_session, user_id=user.id, task_id=task.id, day=day)
    await db_session.flush()


async def _work(
    db_session: AsyncSession,
    task_id: uuid.UUID,
    at: datetime,
    finished_at: datetime | None = None,
) -> None:
    """Нода, начатая в `at` и законченная в `finished_at` (по умолчанию — тогда же)."""
    db_session.add(
        NodeLog(
            task_id=task_id,
            trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
            status=NodeLogStatus.SUCCESS,
            started_at=at,
            finished_at=finished_at or at,
        ),
    )
    await db_session.flush()


async def _event(
    db_session: AsyncSession,
    user: User,
    day: date,
    title: str,
    **fields: object,
) -> DailyEvent:
    values: dict[str, object] = {"source": DailyEventSource.MANUAL, "end_day": day, "hidden": False}
    values.update(fields)
    event = DailyEvent(user_id=user.id, day=day, title=title, **values)
    db_session.add(event)
    await db_session.flush()
    return event


class TestDayMarks:
    @pytest.mark.parametrize("day", [TODAY, TOMORROW], ids=["сегодня", "завтра"])
    async def test_mark_and_unmark(self, db_session: AsyncSession, user: User, day: date) -> None:
        task = await _task(db_session, user)

        await set_day_mark(db_session, user=user, task_id=task.id, day=day, now=NOW)
        await set_day_mark(db_session, user=user, task_id=task.id, day=day, now=NOW)
        marks = await recent_day_marks(db_session, user=user, now=NOW)
        assert [(mark.task_id, mark.days) for mark in marks] == [(task.id, [day])]

        await clear_day_mark(db_session, user=user, task_id=task.id, day=day, now=NOW)
        assert await recent_day_marks(db_session, user=user, now=NOW) == []

    @pytest.mark.parametrize("day", [YESTERDAY, date(2026, 11, 18)], ids=["вчера", "послезавтра"])
    async def test_only_today_or_tomorrow(
        self,
        db_session: AsyncSession,
        user: User,
        day: date,
    ) -> None:
        task = await _task(db_session, user)

        with pytest.raises(ValidationError):
            await set_day_mark(db_session, user=user, task_id=task.id, day=day, now=NOW)
        with pytest.raises(ValidationError):
            await clear_day_mark(db_session, user=user, task_id=task.id, day=day, now=NOW)

    async def test_archived_task_rejected(self, db_session: AsyncSession, user: User) -> None:
        task = await _task(db_session, user, status=TaskStatus.ARCHIVED)

        with pytest.raises(ConflictError):
            await set_day_mark(db_session, user=user, task_id=task.id, day=TODAY, now=NOW)

    async def test_foreign_task_hidden(self, db_session: AsyncSession, user: User) -> None:
        foreign = await make_task(db_session)

        with pytest.raises(NotFoundError):
            await set_day_mark(db_session, user=user, task_id=foreign.id, day=TODAY, now=NOW)

    async def test_marks_are_personal(self, db_session: AsyncSession, user: User) -> None:
        task = await _task(db_session, user)
        other = await make_user(db_session)
        await _mark(db_session, other, task, TODAY)

        assert await recent_day_marks(db_session, user=user, now=NOW) == []

    async def test_recent_window(self, db_session: AsyncSession, user: User) -> None:
        task = await _task(db_session, user)
        for day in (date(2026, 11, 14), YESTERDAY, TODAY, TOMORROW):
            await _mark(db_session, user, task, day)

        (marks,) = await recent_day_marks(db_session, user=user, now=NOW)
        assert marks.days == [YESTERDAY, TODAY, TOMORROW]


class TestDayFacts:
    @pytest.mark.parametrize(
        ("work_at", "fact"),
        [
            (YESTERDAY_START, DayFact.WORKED),
            (TODAY_START - timedelta(seconds=1), DayFact.WORKED),
            (TODAY_START, DayFact.NO_WORK),
            (YESTERDAY_START - timedelta(seconds=1), DayFact.NO_WORK),
        ],
        ids=["начало-дня", "конец-дня", "следующий-день", "предыдущий-день"],
    )
    async def test_work_within_day(
        self,
        db_session: AsyncSession,
        user: User,
        work_at: datetime,
        fact: DayFact,
    ) -> None:
        task = await _task(db_session, user)
        await _mark(db_session, user, task, YESTERDAY)
        await _work(db_session, task.id, work_at)

        view = await day_view(
            db_session,
            user=user,
            day=YESTERDAY,
            clock=CLOCK,
            include_hidden=False,
        )

        assert [item.fact for item in view.tasks] == [fact]

    @pytest.mark.parametrize(
        ("started_at", "finished_at"),
        [
            (YESTERDAY_START - timedelta(hours=2), YESTERDAY_START + timedelta(hours=1)),
            (TODAY_START - timedelta(hours=1), TODAY_START + timedelta(hours=2)),
        ],
        ids=["начата-накануне", "закончена-назавтра"],
    )
    async def test_node_crossing_day_border(
        self,
        db_session: AsyncSession,
        user: User,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        """Нода, которая шла через границу дня, — работа в обоих днях."""
        task = await _task(db_session, user)
        await _mark(db_session, user, task, YESTERDAY)
        await _work(db_session, task.id, started_at, finished_at)

        view = await day_view(
            db_session,
            user=user,
            day=YESTERDAY,
            clock=CLOCK,
            include_hidden=False,
        )

        assert [item.fact for item in view.tasks] == [DayFact.WORKED]

    @pytest.mark.parametrize(
        ("status", "archived_from", "fact"),
        [
            (TaskStatus.DONE, None, DayFact.DONE),
            (TaskStatus.FAILED, None, DayFact.FAILED),
            (TaskStatus.ARCHIVED, TaskStatus.DONE, DayFact.DONE),
            (TaskStatus.ARCHIVED, TaskStatus.FAILED, DayFact.FAILED),
        ],
    )
    async def test_finished_in_day(
        self,
        db_session: AsyncSession,
        user: User,
        status: TaskStatus,
        archived_from: TaskStatus | None,
        fact: DayFact,
    ) -> None:
        task = await _task(
            db_session,
            user,
            status=status,
            archived_from_status=archived_from,
            finished_at=YESTERDAY_START + timedelta(hours=3),
        )
        await _mark(db_session, user, task, YESTERDAY)

        view = await day_view(
            db_session,
            user=user,
            day=YESTERDAY,
            clock=CLOCK,
            include_hidden=False,
        )

        assert [item.fact for item in view.tasks] == [fact]

    async def test_future_day_without_fact(self, db_session: AsyncSession, user: User) -> None:
        task = await _task(db_session, user)
        await _mark(db_session, user, task, TOMORROW)

        view = await day_view(
            db_session,
            user=user,
            day=TOMORROW,
            clock=CLOCK,
            include_hidden=False,
        )

        assert [(item.id, item.fact) for item in view.tasks] == [(task.id, None)]


class TestPreviousDay:
    async def test_skips_days_without_activity(self, db_session: AsyncSession, user: User) -> None:
        """В понедельник прошлый день — пятница: в выходные ничего не отмечено."""
        friday = date(2026, 11, 13)
        task = await _task(db_session, user)
        await _mark(db_session, user, task, friday)
        await _work(db_session, task.id, datetime(2026, 11, 13, 9, 0, tzinfo=UTC))

        previous = await previous_day(db_session, user=user, before=TODAY, clock=CLOCK)

        assert previous.day == friday
        assert [item.id for item in previous.done] == [task.id]

    async def test_done_is_marked_and_worked(self, db_session: AsyncSession, user: User) -> None:
        worked = await _task(db_session, user, "worked")
        idle = await _task(db_session, user, "idle")
        unmarked = await _task(db_session, user, "unmarked")
        for task in (worked, idle):
            await _mark(db_session, user, task, YESTERDAY)
        for task in (worked, unmarked):
            await _work(db_session, task.id, YESTERDAY_START + timedelta(hours=2))

        previous = await previous_day(db_session, user=user, before=TODAY, clock=CLOCK)

        assert [item.title for item in previous.done] == ["worked"]

    async def test_event_counts_as_activity(self, db_session: AsyncSession, user: User) -> None:
        await _event(db_session, user, date(2026, 11, 12), "Ретро")
        await _event(db_session, user, date(2026, 11, 14), "Скрытое", hidden=True)

        previous = await previous_day(db_session, user=user, before=TODAY, clock=CLOCK)

        assert previous.day == date(2026, 11, 12)
        assert [event.title for event in previous.events] == ["Ретро"]

    async def test_no_activity(self, db_session: AsyncSession, user: User) -> None:
        previous = await previous_day(db_session, user=user, before=TODAY, clock=CLOCK)

        assert (previous.day, previous.done, previous.events) == (None, [], [])


class TestDayEvents:
    async def test_create_with_time(self, db_session: AsyncSession, user: User) -> None:
        event = await create_manual_event(
            db_session,
            user=user,
            values=ManualEventValues(
                day=TODAY,
                title="  Созвон  ",
                start_time=time(10, 0),
                end_time=time(11, 0),
            ),
            clock=CLOCK,
        )

        assert (event.title, event.day, event.end_day) == ("Созвон", TODAY, TODAY)
        assert event.starts_at == datetime(2026, 11, 16, 7, 0, tzinfo=UTC)
        assert event.ends_at == datetime(2026, 11, 16, 8, 0, tzinfo=UTC)

    @pytest.mark.parametrize(
        "values",
        [
            ManualEventValues(day=TODAY, title="   "),
            ManualEventValues(day=TODAY, title="x" * 201),
            ManualEventValues(day=TODAY, title="t", notes="x" * 2001),
            ManualEventValues(day=TODAY, title="t", end_time=time(11, 0)),
            ManualEventValues(day=TODAY, title="t", start_time=time(11, 0), end_time=time(10, 0)),
            ManualEventValues(day=date(2026, 11, 8), title="t"),
            ManualEventValues(day=date(2026, 11, 18), title="t"),
        ],
        ids=[
            "пустое-название",
            "длинное-название",
            "длинная-заметка",
            "конец-без-начала",
            "конец-раньше-начала",
            "раньше-окна",
            "позже-завтра",
        ],
    )
    async def test_rejects_invalid(
        self,
        db_session: AsyncSession,
        user: User,
        values: ManualEventValues,
    ) -> None:
        with pytest.raises(ValidationError):
            await create_manual_event(db_session, user=user, values=values, clock=CLOCK)

    async def test_night_end_after_midnight(self, db_session: AsyncSession, user: User) -> None:
        """23:00–01:00 — одно событие дня: конец приходится на ночь после него."""
        event = await create_manual_event(
            db_session,
            user=user,
            values=ManualEventValues(
                day=TODAY,
                title="Релиз",
                start_time=time(23, 0),
                end_time=time(1, 0),
            ),
            clock=CLOCK,
        )

        assert event.ends_at == datetime(2026, 11, 16, 22, 0, tzinfo=UTC)

    async def test_calendar_event_only_hidden(self, db_session: AsyncSession, user: User) -> None:
        event = await _event(
            db_session,
            user,
            TODAY,
            "Планёрка",
            source=DailyEventSource.GOOGLE,
            calendar_id="primary",
            external_id="evt-1",
        )
        values = ManualEventValues(day=TODAY, title="Другое")

        with pytest.raises(ConflictError):
            await update_manual_event(
                db_session,
                user=user,
                event_id=event.id,
                values=values,
                clock=CLOCK,
            )
        with pytest.raises(ConflictError):
            await delete_manual_event(db_session, user=user, event_id=event.id)
        hidden = await set_event_hidden(db_session, user=user, event_id=event.id, hidden=True)
        assert hidden.hidden is True

    async def test_foreign_event_hidden(self, db_session: AsyncSession, user: User) -> None:
        event = await _event(db_session, await make_user(db_session), TODAY, "Чужое")

        with pytest.raises(NotFoundError):
            await set_event_hidden(db_session, user=user, event_id=event.id, hidden=True)

    async def test_day_view_order_and_multiday(self, db_session: AsyncSession, user: User) -> None:
        await _event(db_session, user, TODAY, "Встреча", starts_at=TODAY_START + timedelta(hours=2))
        await _event(db_session, user, YESTERDAY, "Отпуск", end_day=TOMORROW)
        await _event(db_session, user, TODAY, "Скрытое", hidden=True)

        view = await day_view(db_session, user=user, day=TODAY, clock=CLOCK, include_hidden=False)
        with_hidden = await day_view(
            db_session,
            user=user,
            day=TODAY,
            clock=CLOCK,
            include_hidden=True,
        )

        assert [event.title for event in view.events] == ["Отпуск", "Встреча"]
        assert len(with_hidden.events) == 3


class TestDailyTemplate:
    @pytest.mark.parametrize(
        "content",
        ["{{daily.unknown}}", "{{task.title}}", "   ", "x" * 20_001],
        ids=["неизвестное-поле", "чужое-пространство", "пустой", "длинный"],
    )
    def test_rejects_invalid(self, content: str) -> None:
        with pytest.raises(ValidationError):
            validate_daily_template(content)

    async def test_save_and_reset(self, db_session: AsyncSession, user: User) -> None:
        assert (await get_daily_template(db_session, user=user)).is_default is True

        await save_daily_template(db_session, user=user, content="Сегодня: {{daily.today}}")
        saved = await get_daily_template(db_session, user=user)
        assert (saved.content, saved.is_default) == ("Сегодня: {{daily.today}}", False)

        reset = await reset_daily_template(db_session, user=user)
        assert (reset.content, reset.is_default) == (DEFAULT_DAILY_TEMPLATE, True)


class TestDailyPlans:
    async def test_default_template_like_standup(
        self,
        db_session: AsyncSession,
        user: User,
    ) -> None:
        done = await _task(db_session, user, "Подключить вебхуки", code="RR-19384")
        planned = await _task(db_session, user, "Профиль игрока", code="RR-15592")
        await _mark(db_session, user, done, YESTERDAY)
        await _work(db_session, done.id, YESTERDAY_START + timedelta(hours=1))
        await _event(db_session, user, YESTERDAY, "Ревью кода")
        await _mark(db_session, user, planned, TODAY)
        await _event(
            db_session,
            user,
            TODAY,
            "All Hands",
            source=DailyEventSource.GOOGLE,
            calendar_id="primary",
            external_id="evt-1",
            starts_at=TODAY_START + timedelta(hours=3),
        )

        plan = await create_daily_plan(db_session, user=user, day=TODAY, clock=CLOCK)

        assert plan.content == (
            "Доброго всем утра!\n\n"
            "Вчера:\n"
            "• RR-19384: Подключить вебхуки.\n"
            "• Ревью кода.\n\n"
            "Сегодня:\n"
            "• Встреча: All Hands.\n"
            "• RR-15592: Профиль игрока.\n"
        )

    async def test_custom_template_and_empty_lists(
        self,
        db_session: AsyncSession,
        user: User,
    ) -> None:
        await save_daily_template(
            db_session,
            user=user,
            content="{{daily.date}} / {{daily.previous_date}}\n{{daily.done}}\n{{daily.events}}",
        )

        plan = await create_daily_plan(db_session, user=user, day=TODAY, clock=CLOCK)

        assert plan.content == "16.11.2026 / —\n—\n—"

    async def test_one_plan_per_day(self, db_session: AsyncSession, user: User) -> None:
        await create_daily_plan(db_session, user=user, day=TODAY, clock=CLOCK)

        with pytest.raises(ConflictError):
            await create_daily_plan(db_session, user=user, day=TODAY, clock=CLOCK)

    async def test_day_outside_window(self, db_session: AsyncSession, user: User) -> None:
        with pytest.raises(ValidationError):
            await create_daily_plan(db_session, user=user, day=date(2026, 11, 18), clock=CLOCK)

    async def test_regenerate_replaces_text(self, db_session: AsyncSession, user: User) -> None:
        plan = await create_daily_plan(db_session, user=user, day=TODAY, clock=CLOCK)
        plan.content = "правка"
        await _mark(db_session, user, await _task(db_session, user, "Новая", code="RR-1"), TODAY)

        regenerated = await regenerate_daily_plan(
            db_session,
            user=user,
            plan_id=plan.id,
            clock=CLOCK,
        )

        assert "• RR-1: Новая." in regenerated.content

    async def test_preview_without_saving(self, db_session: AsyncSession, user: User) -> None:
        preview = await preview_daily_template(
            db_session,
            user=user,
            content="Дата: {{daily.date}}",
            clock=CLOCK,
        )

        assert preview == "Дата: 16.11.2026"
        assert (await get_daily_template(db_session, user=user)).is_default is True

    async def test_clock_from_settings(self, db_session: AsyncSession) -> None:
        clock = await load_daily_clock(db_session, now=NOW)

        assert (clock.window.today, clock.day_start) == (TODAY, time(8, 0))
