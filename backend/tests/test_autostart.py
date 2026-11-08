from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import services.autostart as autostart_module
from db.models.enums import AppLogLevel, TaskStatus
from db.models.logs import AppLog
from db.models.tasks import Task
from services.autostart import find_tasks_due_for_autostart, run_scheduled_autostart_check
from services.errors import ConflictError, ValidationError
from services.notifications import NotificationEvent
from services.refining_chat import start_chat
from tasks import periodic
from tests.factories import make_pipeline, make_task, make_user


async def _make_task(
    db_session: AsyncSession,
    *,
    status: TaskStatus = TaskStatus.NEW,
    auto_start_enabled: bool = True,
    scheduled_start_at: datetime | None = None,
) -> Task:
    owner = await make_user(db_session)
    pipeline = await make_pipeline(db_session, created_by=owner.id)
    return await make_task(
        db_session,
        created_by=owner.id,
        pipeline_id=pipeline.id,
        status=status,
        auto_start_enabled=auto_start_enabled,
        scheduled_start_at=scheduled_start_at,
    )


async def test_find_tasks_due_for_autostart_matches_past_scheduled_time(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    due_task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))

    found = await find_tasks_due_for_autostart(db_session, now=now)

    assert due_task.id in {task.id for task in found}


async def test_find_tasks_due_for_autostart_excludes_future_schedule(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    await _make_task(db_session, scheduled_start_at=now + timedelta(minutes=5))

    found = await find_tasks_due_for_autostart(db_session, now=now)

    assert found == []


async def test_find_tasks_due_for_autostart_excludes_disabled_autostart(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    await _make_task(
        db_session,
        auto_start_enabled=False,
        scheduled_start_at=now - timedelta(minutes=1),
    )

    found = await find_tasks_due_for_autostart(db_session, now=now)

    assert found == []


async def test_find_tasks_due_for_autostart_excludes_non_new_status(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    await _make_task(
        db_session,
        status=TaskStatus.IN_PROGRESS,
        scheduled_start_at=now - timedelta(minutes=1),
    )

    found = await find_tasks_due_for_autostart(db_session, now=now)

    assert found == []


async def test_run_scheduled_autostart_check_transitions_to_ready(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))

    result = await run_scheduled_autostart_check(db_session, now=now)

    assert task.id in result.queued_task_ids
    await db_session.refresh(task)
    assert (task.status, task.auto_start_enabled) == (TaskStatus.READY, False)


async def test_run_scheduled_autostart_check_is_idempotent_within_same_window(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))

    first = await run_scheduled_autostart_check(db_session, now=now)
    second = await run_scheduled_autostart_check(db_session, now=now)

    assert task.id in first.queued_task_ids
    assert second.queued_task_ids == []


async def test_run_scheduled_autostart_check_one_failure_does_not_block_others(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Раздел 12.3: сбой инициации ОДНОЙ задачи не прерывает обработку пачки.

    Настоящая гонка (задача меняет статус между SELECT и UPDATE) требует
    двух параллельных соединений к БД — `AsyncSession` не поддерживает
    конкурентное использование из двух корутин. Вместо этого здесь
    `transition_task_status` подменяется так, чтобы детерминированно
    отказать для ОДНОЙ конкретной задачи, — так же надёжно проверяет
    именно поведение цикла обработки пачки (раздел 12.3), не завися от
    реального тайминга гонки.
    """
    now = datetime.now(UTC)
    good_task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))
    bad_task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))

    real_transition = autostart_module.transition_task_status  # type: ignore[attr-defined]

    async def _flaky_transition(session: AsyncSession, **kwargs: object) -> Task:
        if kwargs.get("task_id") == bad_task.id:
            raise ConflictError("симулированная гонка статуса")
        return await real_transition(session, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(autostart_module, "transition_task_status", _flaky_transition)

    result = await run_scheduled_autostart_check(db_session, now=now)

    assert good_task.id in result.queued_task_ids
    assert bad_task.id in result.failed_task_ids

    logs_stmt = sa.select(AppLog).where(
        AppLog.task_id == bad_task.id,
        AppLog.level == AppLogLevel.ERROR,
    )
    logs = (await db_session.execute(logs_stmt)).scalars().all()
    assert len(logs) == 1
    assert logs[0].source == "autostart"


async def test_periodic_autostart_wakes_dispatcher_for_queued_tasks(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Раздел 12.2: задача встала в `ready` — её сразу забирает воркер очереди."""
    due_task = await _make_task(
        db_session,
        scheduled_start_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    captured_bodies: list[object] = []
    wakes: list[None] = []
    monkeypatch.setattr(periodic, "_run_periodic", lambda _name, body: captured_bodies.append(body))
    monkeypatch.setattr(periodic, "wake_task_dispatcher", lambda: wakes.append(None))

    periodic.check_scheduled_tasks_for_autostart()
    [body] = captured_bodies
    await body(db_session)  # type: ignore[operator]

    await db_session.refresh(due_task)
    assert (due_task.status, wakes) == (TaskStatus.READY, [None])


class TestRepositoryEnvConflict:
    async def test_autostart_fails_with_notification(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Решение 2026-10-20: конфликт переменных репозиториев — ошибка до запуска."""
        now = datetime.now(UTC)
        task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))
        events: list[NotificationEvent] = []

        async def capture(_db: AsyncSession, *, event: NotificationEvent, **_: object) -> None:
            events.append(event)

        async def conflict(_db: AsyncSession, _task: Task) -> None:
            raise ValidationError("Переменная API_URL задана в нескольких репозиториях задачи")

        monkeypatch.setattr(autostart_module, "notify_task_event", capture)
        monkeypatch.setattr(autostart_module, "ensure_task_launchable", conflict)

        result = await run_scheduled_autostart_check(db_session, now=now)

        assert result.failed_task_ids == [task.id]
        assert events == [NotificationEvent.AUTOSTART_FAILED]
        await db_session.refresh(task)
        assert task.status is TaskStatus.NEW


async def test_chat_started_after_selection_defers_autostart(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = await _make_task(
        db_session,
        status=TaskStatus.REFINING,
        scheduled_start_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    async def chat_begins(db: AsyncSession, candidate: Task) -> None:
        assert await start_chat(db, task_id=candidate.id) is not None

    monkeypatch.setattr(autostart_module, "ensure_task_launchable", chat_begins)
    result = await run_scheduled_autostart_check(db_session, now=datetime.now(UTC))

    await db_session.refresh(task)
    assert (task.status, task.chat_active, task.auto_start_enabled) == (
        TaskStatus.REFINING,
        True,
        True,
    )
    assert result.queued_task_ids == result.failed_task_ids == []
