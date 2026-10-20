import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import services.autostart as autostart_module
from db.models.enums import AppLogLevel, TaskStatus, UserRole
from db.models.logs import AppLog
from db.models.tasks import Task
from db.models.users import User
from services.autostart import find_tasks_due_for_autostart, run_scheduled_autostart_check
from services.errors import ConflictError, ValidationError
from services.notifications import NotificationEvent
from tasks import periodic, session_worker


async def _make_task(
    db_session: AsyncSession,
    *,
    status: TaskStatus = TaskStatus.NEW,
    auto_start_enabled: bool = True,
    scheduled_start_at: datetime | None = None,
) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        status=status,
        auto_start_enabled=auto_start_enabled,
        scheduled_start_at=scheduled_start_at,
    )
    db_session.add(task)
    await db_session.flush()
    return task


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


async def test_run_scheduled_autostart_check_transitions_to_queued(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))

    result = await run_scheduled_autostart_check(db_session, now=now)

    assert task.id in result.started_task_ids
    await db_session.refresh(task)
    assert task.status is TaskStatus.QUEUED


async def test_run_scheduled_autostart_check_is_idempotent_within_same_window(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    task = await _make_task(db_session, scheduled_start_at=now - timedelta(minutes=1))

    first = await run_scheduled_autostart_check(db_session, now=now)
    second = await run_scheduled_autostart_check(db_session, now=now)

    assert task.id in first.started_task_ids
    assert second.started_task_ids == []


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

    assert good_task.id in result.started_task_ids
    assert bad_task.id in result.failed_task_ids

    logs_stmt = sa.select(AppLog).where(
        AppLog.task_id == bad_task.id,
        AppLog.level == AppLogLevel.ERROR,
    )
    logs = (await db_session.execute(logs_stmt)).scalars().all()
    assert len(logs) == 1
    assert logs[0].source == "autostart"


async def test_periodic_autostart_enqueues_session_worker_for_started_tasks(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Раздел 12.2: после `new -> queued` задача реально запускается —
    иначе она навсегда осталась бы в `queued`."""
    due_task = await _make_task(
        db_session,
        scheduled_start_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    captured_bodies: list[object] = []
    enqueued_task_ids: list[str] = []
    monkeypatch.setattr(periodic, "_run_periodic", lambda _name, body: captured_bodies.append(body))
    monkeypatch.setattr(session_worker.run_task_session, "delay", enqueued_task_ids.append)

    periodic.check_scheduled_tasks_for_autostart()
    [body] = captured_bodies
    await body(db_session)  # type: ignore[operator]

    assert enqueued_task_ids == [str(due_task.id)]


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

        async def conflict(_db: AsyncSession, *, task_id: uuid.UUID) -> None:
            raise ValidationError("Переменная API_URL задана в нескольких репозиториях задачи")

        monkeypatch.setattr(autostart_module, "notify_task_event", capture)
        monkeypatch.setattr(autostart_module, "ensure_no_repository_env_conflicts", conflict)

        result = await run_scheduled_autostart_check(db_session, now=now)

        assert result.failed_task_ids == [task.id]
        assert events == [NotificationEvent.AUTOSTART_FAILED]
        await db_session.refresh(task)
        assert task.status is TaskStatus.NEW
