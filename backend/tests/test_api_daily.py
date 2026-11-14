"""API «Дейли» (раздел 15.8 ТЗ): дни, отметки задач, события, планы и шаблон."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest

from db.models.daily import DailyEvent, DailyPlan
from db.models.enums import DailyEventSource, TaskStatus
from services.tracker_day import DayWindow
from tests.factories import make_task, make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


def _window() -> DayWindow:
    return DayWindow.at(datetime.now(UTC), time(8, 0))


def _event_body(day: date, **fields: object) -> dict[str, object]:
    return {"day": day.isoformat(), "title": "Созвон", **fields}


class TestCalendar:
    async def test_days(self, authed_client: AsyncClient) -> None:
        response = await authed_client.get("/daily/calendar")

        window = _window()
        body = response.json()
        assert response.status_code == 200
        assert (body["today"], body["tomorrow"], body["day_start_time"]) == (
            window.today.isoformat(),
            window.tomorrow.isoformat(),
            "08:00:00",
        )
        assert body["history_days"] == [day.isoformat() for day in window.history_days()]


class TestDayMarksApi:
    async def test_mark_shown_in_recent(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id)
        today = _window().today.isoformat()

        marked = await authed_client.put(f"/tasks/{task.id}/day-marks/{today}")
        marks = await authed_client.get("/daily/marks")

        assert marked.status_code == 204
        assert marks.json() == [{"task_id": str(task.id), "days": [today]}]
        unmarked = await authed_client.delete(f"/tasks/{task.id}/day-marks/{today}")
        assert unmarked.status_code == 204
        assert (await authed_client.get("/daily/marks")).json() == []

    @pytest.mark.parametrize(
        ("status", "offset", "expected"),
        [
            (TaskStatus.NEW, -1, 422),
            (TaskStatus.ARCHIVED, 0, 409),
        ],
        ids=["вчера", "архивная"],
    )
    async def test_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        status: TaskStatus,
        offset: int,
        expected: int,
    ) -> None:
        task = await make_task(db_session, created_by=current_user.id, status=status)
        day = _window().today + timedelta(days=offset)

        response = await authed_client.put(f"/tasks/{task.id}/day-marks/{day.isoformat()}")

        assert response.status_code == expected

    async def test_foreign_task(self, authed_client: AsyncClient, db_session: AsyncSession) -> None:
        task = await make_task(db_session)

        response = await authed_client.put(f"/tasks/{task.id}/day-marks/{_window().today}")

        assert response.status_code == 404


class TestDayHistoryApi:
    async def test_day_with_tasks_and_events(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        today = _window().today
        task = await make_task(db_session, created_by=current_user.id, code="RR-7", title="Задача")
        await authed_client.put(f"/tasks/{task.id}/day-marks/{today}")
        created = await authed_client.post(
            "/daily/events",
            json=_event_body(today, start_time="10:00", end_time="11:30"),
        )

        response = await authed_client.get(f"/daily/days/{today}")

        assert created.status_code == 201
        assert created.json()["start_time"] == "10:00:00"
        body = response.json()
        assert [(item["code"], item["fact"]) for item in body["tasks"]] == [("RR-7", "no_work")]
        assert [(item["title"], item["end_time"]) for item in body["events"]] == [
            ("Созвон", "11:30:00"),
        ]

    async def test_day_outside_window(self, authed_client: AsyncClient) -> None:
        day = _window().today + timedelta(days=2)

        response = await authed_client.get(f"/daily/days/{day}")

        assert response.status_code == 422


class TestEventsApi:
    async def test_update_hide_delete(self, authed_client: AsyncClient) -> None:
        today = _window().today
        event_id = (await authed_client.post("/daily/events", json=_event_body(today))).json()["id"]

        updated = await authed_client.put(
            f"/daily/events/{event_id}",
            json=_event_body(today, title="Планёрка", notes="Повестка"),
        )
        hidden = await authed_client.put(f"/daily/events/{event_id}/hidden", json={"hidden": True})
        deleted = await authed_client.delete(f"/daily/events/{event_id}")

        assert (updated.json()["title"], updated.json()["notes"]) == ("Планёрка", "Повестка")
        assert hidden.json()["hidden"] is True
        assert deleted.status_code == 204

    @pytest.mark.parametrize(
        "fields",
        [{"title": ""}, {"title": "x" * 201}, {"start_time": "12:00", "end_time": "11:00"}],
        ids=["пустое", "длинное", "конец-раньше"],
    )
    async def test_invalid(self, authed_client: AsyncClient, fields: dict[str, str]) -> None:
        body = _event_body(_window().today, **fields)

        response = await authed_client.post("/daily/events", json=body)

        assert response.status_code == 422

    async def test_personal_even_for_admin(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Записи «Дейли» личные: администратор чужое событие не видит."""
        other = await make_user(db_session)
        today = _window().today
        event = DailyEvent(
            user_id=other.id,
            source=DailyEventSource.MANUAL,
            day=today,
            end_day=today,
            title="Чужое",
            hidden=False,
        )
        db_session.add(event)
        await db_session.flush()

        response = await admin_client.put(f"/daily/events/{event.id}/hidden", json={"hidden": True})

        assert response.status_code == 404


class TestPlansApi:
    async def test_create_edit_regenerate_delete(self, authed_client: AsyncClient) -> None:
        today = _window().today.isoformat()

        created = await authed_client.post("/daily/plans", json={"day": today})
        duplicate = await authed_client.post("/daily/plans", json={"day": today})
        plan_id = created.json()["id"]
        edited = await authed_client.put(f"/daily/plans/{plan_id}", json={"content": "Мой план"})
        regenerated = await authed_client.post(f"/daily/plans/{plan_id}/regenerate")
        listed = await authed_client.get("/daily/plans")
        deleted = await authed_client.delete(f"/daily/plans/{plan_id}")

        assert created.status_code == 201
        assert created.json()["content"].startswith("Доброго всем утра!")
        assert duplicate.status_code == 409
        assert edited.json()["content"] == "Мой план"
        assert regenerated.json()["content"] == created.json()["content"]
        assert [plan["id"] for plan in listed.json()] == [plan_id]
        assert deleted.status_code == 204
        assert (await authed_client.get(f"/daily/plans/{plan_id}")).status_code == 404

    async def test_foreign_plan(self, authed_client: AsyncClient, db_session: AsyncSession) -> None:
        other = await make_user(db_session)
        plan = DailyPlan(user_id=other.id, day=_window().today, content="чужой")
        db_session.add(plan)
        await db_session.flush()

        assert (await authed_client.get(f"/daily/plans/{plan.id}")).status_code == 404


class TestTemplateApi:
    async def test_save_preview_reset(self, authed_client: AsyncClient) -> None:
        initial = await authed_client.get("/daily/template")
        saved = await authed_client.put("/daily/template", json={"content": "{{daily.date}}"})
        preview = await authed_client.post(
            "/daily/template/preview",
            json={"content": "Дата {{daily.date}}"},
        )
        invalid = await authed_client.put("/daily/template", json={"content": "{{daily.nope}}"})
        reset = await authed_client.delete("/daily/template")

        assert initial.json()["is_default"] is True
        assert "daily.today" in initial.json()["variables"]
        assert saved.json() == {**saved.json(), "content": "{{daily.date}}", "is_default": False}
        assert preview.json()["content"] == f"Дата {_window().today.strftime('%d.%m.%Y')}"
        assert invalid.status_code == 422
        assert reset.json()["is_default"] is True
