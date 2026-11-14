"""
API очереди задач (разделы 14.1, 14.2, 14.4, 15.5 ТЗ): ручная смена статуса,
отмена постановки, приоритет и слот, место в очереди, сводка слотов, лимит
пользователя, ночное окно, расписание ночного воркера и чат в «Уточняется».
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa

from db.models.enums import PeriodicScheduleType, TaskStatus
from db.models.periodic import PeriodicTask
from db.models.tasks import Task
from services.periodic_tasks import NIGHT_DISPATCH_TASK
from services.refining_chat import CHAT_BUSY_MESSAGE
from tests.factories import make_llm_account, make_pipeline, make_task

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User

_SETTINGS = {
    "default_timeout_seconds": 900,
    "default_max_retries": 2,
    "default_retry_base_delay_seconds": 10,
    "app_logs_retention_days": 30,
}


@pytest.fixture
def wakes(monkeypatch: pytest.MonkeyPatch) -> list[None]:
    """Пробуждения воркера очереди из API — без брокера Celery."""
    calls: list[None] = []
    for module in ("api.tasks.lifecycle", "api.tasks.crud", "api.users"):
        monkeypatch.setattr(f"{module}.wake_task_dispatcher", lambda: calls.append(None))
    return calls


async def _task(
    db_session: AsyncSession,
    owner: User,
    status: TaskStatus,
    **fields: Any,
) -> Task:
    pipeline = await make_pipeline(db_session, created_by=owner.id)
    task = await make_task(
        db_session,
        created_by=owner.id,
        status=status,
        pipeline_id=pipeline.id,
        **fields,
    )
    await db_session.flush()
    return task


class TestStatusChange:
    @pytest.mark.parametrize(
        ("from_status", "to_status", "woken"),
        [
            pytest.param(TaskStatus.NEW, TaskStatus.READY, True, id="в очередь"),
            pytest.param(TaskStatus.DEFINED, TaskStatus.REFINING, True, id="до запуска"),
            pytest.param(TaskStatus.DONE, TaskStatus.NIGHT_WORKER, True, id="из done"),
        ],
    )
    async def test_changed(
        self,
        *,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        wakes: list[None],
        from_status: TaskStatus,
        to_status: TaskStatus,
        woken: bool,
    ) -> None:
        task = await _task(db_session, current_user, from_status)

        response = await authed_client.post(
            f"/tasks/{task.id}/status",
            json={"to_status": to_status.value},
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == to_status.value
        assert bool(wakes) is woken

    @pytest.mark.parametrize(
        ("from_status", "to_status", "code"),
        [
            pytest.param(TaskStatus.IN_PROGRESS, TaskStatus.NEW, 409, id="в работе"),
            pytest.param(TaskStatus.NEW, TaskStatus.QUEUED, 422, id="не до запуска"),
        ],
    )
    async def test_rejected(
        self,
        *,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        wakes: list[None],
        from_status: TaskStatus,
        to_status: TaskStatus,
        code: int,
    ) -> None:
        task = await _task(db_session, current_user, from_status)

        response = await authed_client.post(
            f"/tasks/{task.id}/status",
            json={"to_status": to_status.value},
        )

        assert response.status_code == code
        assert wakes == []

    async def test_foreign_task_hidden(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        wakes: list[None],
    ) -> None:
        task = await _task(db_session, admin_user, TaskStatus.NEW)

        response = await authed_client.post(
            f"/tasks/{task.id}/status",
            json={"to_status": TaskStatus.READY.value},
        )

        assert response.status_code == 404


class TestCancel:
    @pytest.mark.parametrize(
        ("queued_from", "expected"),
        [
            pytest.param(None, TaskStatus.NEW, id="без исходного статуса"),
            pytest.param(TaskStatus.REFINING, TaskStatus.REFINING, id="из уточнения"),
            pytest.param(TaskStatus.READY, TaskStatus.DEFINED, id="из очереди"),
            pytest.param(TaskStatus.NIGHT_WORKER, TaskStatus.DEFINED, id="из ночной очереди"),
        ],
    )
    async def test_target(
        self,
        *,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        wakes: list[None],
        queued_from: TaskStatus | None,
        expected: TaskStatus,
    ) -> None:
        task = await _task(
            db_session,
            current_user,
            TaskStatus.QUEUED,
            queued_from_status=queued_from,
        )

        response = await authed_client.post(f"/tasks/{task.id}/cancel")

        assert response.status_code == 200, response.text
        await db_session.refresh(task)
        assert (task.status, task.queued_from_status, wakes) == (expected, None, [None])


class TestRunControlFields:
    @pytest.mark.parametrize("status", [TaskStatus.NEW, TaskStatus.IN_PROGRESS, TaskStatus.DONE])
    async def test_any_status(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        status: TaskStatus,
    ) -> None:
        task = await _task(db_session, current_user, status)

        response = await authed_client.patch(
            f"/tasks/{task.id}",
            json={"queue_priority": 250, "occupies_slot": True},
        )

        assert response.status_code == 200, response.text
        assert (response.json()["queue_priority"], response.json()["occupies_slot"]) == (250, True)

    @pytest.mark.parametrize(
        ("before", "after", "woken"),
        [(True, False, True), (False, False, False), (False, True, False), (True, True, False)],
    )
    async def test_released_slot_wakes_dispatcher(
        self,
        *,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        wakes: list[None],
        before: bool,
        after: bool,
        woken: bool,
    ) -> None:
        task = await _task(
            db_session,
            current_user,
            TaskStatus.IN_PROGRESS,
            launched_manually=True,
            occupies_slot=before,
        )

        response = await authed_client.patch(f"/tasks/{task.id}", json={"occupies_slot": after})

        assert response.status_code == 200, response.text
        assert bool(wakes) is woken

    @pytest.mark.parametrize("priority", [0, 1_000_001])
    async def test_priority_range(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        priority: int,
    ) -> None:
        task = await _task(db_session, current_user, TaskStatus.NEW)

        response = await authed_client.patch(
            f"/tasks/{task.id}",
            json={"queue_priority": priority},
        )

        assert response.status_code == 422

    async def test_other_fields_after_launch(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await _task(db_session, current_user, TaskStatus.IN_PROGRESS)

        response = await authed_client.patch(
            f"/tasks/{task.id}",
            json={"title": "Другое", "queue_priority": 5},
        )

        assert response.status_code == 422


class TestQueueView:
    async def test_positions_and_summary(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        now = datetime.now(UTC)
        later = await _task(
            db_session,
            current_user,
            TaskStatus.READY,
            ready_at=now - timedelta(minutes=5),
        )
        urgent = await _task(
            db_session,
            current_user,
            TaskStatus.NIGHT_WORKER,
            ready_at=now,
            queue_priority=500,
        )
        running = await _task(db_session, current_user, TaskStatus.IN_PROGRESS)

        listed = {item["id"]: item for item in (await authed_client.get("/tasks")).json()}
        single = (await authed_client.get(f"/tasks/{later.id}")).json()
        summary = (await authed_client.get("/tasks/queue-summary")).json()

        assert listed[str(urgent.id)]["queue_position"] == 1
        assert single["queue_position"] == 2
        assert listed[str(running.id)]["queue_position"] is None
        assert summary == {
            "max_parallel_tasks": current_user.max_parallel_tasks,
            "occupied": 1,
            "ready": 1,
            "night_worker": 1,
        }


class TestUserLimit:
    @pytest.mark.parametrize(
        ("limit", "woken"),
        [pytest.param(5, True, id="поднят"), pytest.param(2, False, id="снижен")],
    )
    async def test_updated(
        self,
        admin_client: AsyncClient,
        current_user: User,
        wakes: list[None],
        limit: int,
        woken: bool,
    ) -> None:
        response = await admin_client.patch(
            f"/users/{current_user.id}",
            json={"max_parallel_tasks": limit},
        )

        assert response.status_code == 200, response.text
        assert response.json()["max_parallel_tasks"] == limit
        assert bool(wakes) is woken

    @pytest.mark.parametrize("limit", [0, 51])
    async def test_range(
        self,
        admin_client: AsyncClient,
        current_user: User,
        wakes: list[None],
        limit: int,
    ) -> None:
        response = await admin_client.patch(
            f"/users/{current_user.id}",
            json={"max_parallel_tasks": limit},
        )

        assert response.status_code == 422


class TestNightWindow:
    async def _night_task(self, db_session: AsyncSession) -> PeriodicTask:
        await db_session.execute(
            sa.delete(PeriodicTask).where(PeriodicTask.name == NIGHT_DISPATCH_TASK),
        )
        periodic_task = PeriodicTask(
            id=uuid.uuid4(),
            name=NIGHT_DISPATCH_TASK,
            display_name="Ночной воркер очереди",
            description="",
            task_path="tasks.periodic.dispatch_night_tasks",
            schedule_type=PeriodicScheduleType.CRONTAB,
            crontab_expression="15 0 * * *",
        )
        db_session.add(periodic_task)
        await db_session.flush()
        return periodic_task

    async def test_start_moves_schedule(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        periodic_task = await self._night_task(db_session)

        response = await admin_client.put(
            "/system-settings",
            json={**_SETTINGS, "night_window_start": "01:40:00", "night_window_end": "06:00:00"},
        )

        assert response.status_code == 200, response.text
        await db_session.refresh(periodic_task)
        assert periodic_task.crontab_expression == "40 22 * * *"

    async def test_equal_bounds_rejected(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        periodic_task = await self._night_task(db_session)

        response = await admin_client.put(
            "/system-settings",
            json={**_SETTINGS, "night_window_start": "04:00:00", "night_window_end": "04:00:00"},
        )

        assert response.status_code == 422
        await db_session.refresh(periodic_task)
        assert periodic_task.crontab_expression == "15 0 * * *"

    async def test_schedule_not_editable(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        periodic_task = await self._night_task(db_session)

        response = await admin_client.patch(
            f"/periodic-tasks/{periodic_task.id}",
            json={"crontab_expression": "0 1 * * *"},
        )

        assert response.status_code == 422
        assert "ночного окна" in response.json()["error"]["message"]


@pytest.fixture
def chat_wakes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """
    Как запрос будит сессию: новый проход чата или сигнал живому воркеру.
    """
    calls: list[tuple[str, Any]] = []

    def delay(task_id: str, **kwargs: Any) -> None:
        calls.append(("delay", kwargs))

    async def signal(task_id: uuid.UUID) -> None:
        calls.append(("signal", None))

    monkeypatch.setattr("api.tasks.common.run_task_session", SimpleNamespace(delay=delay))
    monkeypatch.setattr("api.tasks.common.publish_signal", signal)
    return calls


class TestRefiningChat:
    async def _chat_task(
        self,
        db_session: AsyncSession,
        owner: User,
        status: TaskStatus = TaskStatus.REFINING,
        **fields: Any,
    ) -> Task:
        account = await make_llm_account(db_session, owner_id=owner.id)
        return await _task(db_session, owner, status, llm_account_id=account.id, **fields)

    @pytest.mark.parametrize(
        ("chat_active", "expected"),
        [
            pytest.param(False, [("delay", {"chat_only": True})], id="новый проход"),
            pytest.param(True, [("signal", None)], id="чат уже идёт"),
        ],
    )
    async def test_freeform_wakes_chat(
        self,
        *,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        chat_wakes: list[tuple[str, Any]],
        chat_active: bool,
        expected: list[tuple[str, Any]],
    ) -> None:
        task = await self._chat_task(db_session, current_user, chat_active=chat_active)

        response = await authed_client.post(
            f"/tasks/{task.id}/freeform",
            json={"raw_prompt_text": "Что уточнить?"},
        )

        assert response.status_code == 201, response.text
        assert chat_wakes == expected
        task_body = (await authed_client.get(f"/tasks/{task.id}")).json()
        assert task_body["chat_active"] is chat_active

    async def test_other_pre_launch_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        chat_wakes: list[tuple[str, Any]],
    ) -> None:
        task = await self._chat_task(db_session, current_user, TaskStatus.DEFINED)

        response = await authed_client.post(
            f"/tasks/{task.id}/freeform",
            json={"raw_prompt_text": "Что уточнить?"},
        )

        assert response.status_code == 409
        assert chat_wakes == []

    async def test_llm_account_required(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        chat_wakes: list[tuple[str, Any]],
    ) -> None:
        task = await _task(db_session, current_user, TaskStatus.REFINING)

        response = await authed_client.post(
            f"/tasks/{task.id}/freeform",
            json={"raw_prompt_text": "Что уточнить?"},
        )

        assert response.status_code == 422
        assert chat_wakes == []

    async def test_status_change_waits_for_answer(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        wakes: list[None],
    ) -> None:
        task = await self._chat_task(db_session, current_user, chat_active=True)

        response = await authed_client.post(
            f"/tasks/{task.id}/status",
            json={"to_status": TaskStatus.DEFINED.value},
        )

        assert response.status_code == 409
        assert response.json()["error"]["message"] == CHAT_BUSY_MESSAGE

    async def test_start_waits_for_answer(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await self._chat_task(db_session, current_user, chat_active=True)

        response = await authed_client.post(f"/tasks/{task.id}/start")

        assert response.status_code == 409
        assert response.json()["error"]["message"] == CHAT_BUSY_MESSAGE


class TestLimitWaitControl:
    """
    Раздел 14.2, 19.7: у ждущей лимита задачи воркера нет — её останавливает
    и ставит на паузу API.
    """

    _UNTIL = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)

    async def _waiting(
        self,
        db_session: AsyncSession,
        owner: User,
        from_status: TaskStatus,
    ) -> Task:
        return await _task(
            db_session,
            owner,
            TaskStatus.AWAITING_LIMIT,
            limit_wait_from_status=from_status,
            limit_wait_until=self._UNTIL,
            limit_wait_order_index=None if from_status is TaskStatus.REFINING else 2,
        )

    @pytest.mark.parametrize(
        ("from_status", "status", "restart"),
        [
            pytest.param(TaskStatus.IN_PROGRESS, TaskStatus.FAILED, 2, id="из работы"),
            pytest.param(TaskStatus.REFINING, TaskStatus.REFINING, None, id="из чата"),
        ],
    )
    async def test_stop(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        wakes: list[None],
        from_status: TaskStatus,
        status: TaskStatus,
        restart: int | None,
    ) -> None:
        task = await self._waiting(db_session, current_user, from_status)

        response = await authed_client.post(f"/tasks/{task.id}/stop")

        assert response.status_code == 202, response.text
        await db_session.refresh(task)
        assert (task.status, task.last_failed_order_index) == (status, restart)
        assert (task.limit_wait_from_status, task.limit_wait_until) == (None, None)
        assert len(wakes) == 1

    @pytest.mark.parametrize(
        ("from_status", "code", "expected_from"),
        [
            pytest.param(TaskStatus.IN_PROGRESS, 202, TaskStatus.PAUSED, id="из работы"),
            pytest.param(TaskStatus.REFINING, 409, TaskStatus.REFINING, id="из чата"),
        ],
    )
    async def test_pause(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
        from_status: TaskStatus,
        code: int,
        expected_from: TaskStatus,
    ) -> None:
        task = await self._waiting(db_session, current_user, from_status)

        response = await authed_client.post(f"/tasks/{task.id}/pause")

        assert response.status_code == code, response.text
        await db_session.refresh(task)
        assert (task.status, task.limit_wait_from_status) == (
            TaskStatus.AWAITING_LIMIT,
            expected_from,
        )

    async def test_resume_rejected(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await self._waiting(db_session, current_user, TaskStatus.PAUSED)

        response = await authed_client.post(f"/tasks/{task.id}/resume")

        assert response.status_code == 409

    @pytest.mark.usefixtures("redis_client")
    async def test_freeform_queued(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)
        task = await self._waiting(db_session, current_user, TaskStatus.IN_PROGRESS)
        task.llm_account_id = account.id
        await db_session.flush()

        response = await authed_client.post(
            f"/tasks/{task.id}/freeform",
            json={"raw_prompt_text": "после сброса"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "queued"

    async def test_task_fields(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        task = await self._waiting(db_session, current_user, TaskStatus.PAUSED)

        body = (await authed_client.get(f"/tasks/{task.id}")).json()

        assert body["status"] == "awaiting_limit"
        assert body["limit_wait_from_status"] == "paused"
        assert datetime.fromisoformat(body["limit_wait_until"]) == self._UNTIL


class TestLlmLimit:
    async def test_no_wait(self, authed_client: AsyncClient) -> None:
        response = await authed_client.get("/tasks/llm-limit")

        assert (response.status_code, response.json()) == (200, {"wait_until": None})

    async def test_own_nearest_wait(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        current_user: User,
    ) -> None:
        soon = datetime.now(UTC) + timedelta(hours=1)
        for owner_id, until in [
            (current_user.id, soon + timedelta(hours=2)),
            (current_user.id, soon),
            (None, soon - timedelta(minutes=30)),
        ]:
            await make_task(
                db_session,
                created_by=owner_id,
                status=TaskStatus.AWAITING_LIMIT,
                limit_wait_from_status=TaskStatus.IN_PROGRESS,
                limit_wait_until=until,
            )

        response = await authed_client.get("/tasks/llm-limit")

        assert datetime.fromisoformat(response.json()["wait_until"]) == soon


class TestLlmLimitOfAuthor:
    """Подсказка у «Выполнить» — по ожиданию автора задачи, а не смотрящего."""

    _UNTIL = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)

    async def _author_waiting(self, db_session: AsyncSession) -> uuid.UUID:
        task = await make_task(
            db_session,
            status=TaskStatus.AWAITING_LIMIT,
            limit_wait_from_status=TaskStatus.IN_PROGRESS,
            limit_wait_until=self._UNTIL,
        )
        return task.created_by

    async def test_admin_sees_author_wait(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        author_id = await self._author_waiting(db_session)

        response = await admin_client.get("/tasks/llm-limit", params={"author_id": str(author_id)})

        assert datetime.fromisoformat(response.json()["wait_until"]) == self._UNTIL

    async def test_user_cannot_see_other_author(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        author_id = await self._author_waiting(db_session)

        response = await authed_client.get("/tasks/llm-limit", params={"author_id": str(author_id)})

        assert response.status_code == 403

    async def test_own_author_id(
        self,
        authed_client: AsyncClient,
        current_user: User,
    ) -> None:
        response = await authed_client.get(
            "/tasks/llm-limit",
            params={"author_id": str(current_user.id)},
        )

        assert (response.status_code, response.json()) == (200, {"wait_until": None})
