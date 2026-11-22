import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from clients.claude_agent import InjectionRefusedError
from db.models.enums import (
    ManualRequestStatus,
    ManualRequestType,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    TaskStatus,
)
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services import prompt_injection
from services.errors import ConflictError
from services.manual_admission import ensure_manual_requests_drained
from services.prompt_injection import (
    REASON_FAILED,
    REASON_NOTHING_TO_CANCEL,
    REASON_NOTHING_TO_INJECT,
    REASON_TOO_LATE,
    InjectionAction,
    InjectionReply,
    InjectionUnavailableError,
    PromptInjector,
    return_leftover_injections,
    send_injection_command,
    serve_injection_commands,
)
from services.task_status import close_turn_after_error
from tests.factories import make_llm_account, make_task, make_user


class _StubSession:
    """Сессия задачи в той части, что нужна исполнителю влития."""

    def __init__(self) -> None:
        self.refusal: str | None = None
        self.injected: list[tuple[str, str]] = []
        self.cancel_result = True
        self.fail_with: Exception | None = None

    def injection_refusal(self) -> str | None:
        return self.refusal

    async def inject_prompt(self, text: str, message_id: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        if self.refusal is not None:
            raise InjectionRefusedError(self.refusal)
        self.injected.append((text, message_id))

    async def cancel_injection(self, message_id: str) -> bool:
        return self.cancel_result


async def _task(db_session: AsyncSession) -> Task:
    user = await make_user(db_session)
    return await make_task(
        db_session,
        created_by=user.id,
        status=TaskStatus.IN_PROGRESS,
        llm_account_id=(await make_llm_account(db_session, owner_id=user.id)).id,
    )


async def _enqueue(
    db_session: AsyncSession,
    task: Task,
    text: str | None,
    *,
    request_type: ManualRequestType = ManualRequestType.FREEFORM_PROMPT,
    offset: int = 0,
    node_id: uuid.UUID | None = None,
) -> TaskManualRequestQueue:
    request = TaskManualRequestQueue(
        task_id=task.id,
        request_type=request_type,
        raw_prompt_text=text,
        node_id=node_id,
        requested_by=task.created_by,
        status=ManualRequestStatus.QUEUED,
        requested_at=datetime.now(UTC) + timedelta(seconds=offset),
    )
    db_session.add(request)
    await db_session.flush()
    return request


def _injector(db_session: AsyncSession, task: Task) -> tuple[PromptInjector, _StubSession]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    injector = PromptInjector(task_id=task.id, session_factory=factory)  # type: ignore[arg-type]
    stub = _StubSession()
    injector.bind(stub)  # type: ignore[arg-type]
    return injector, stub


async def _status(db_session: AsyncSession, request: TaskManualRequestQueue) -> ManualRequestStatus:
    await db_session.refresh(request)
    return request.status


class TestInject:
    """Влитие ближайшего текстового промта."""

    async def test_takes_nearest_skips_commands(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = await _task(db_session)
        command = await _enqueue(db_session, task, "/compact", offset=0)
        first = await _enqueue(db_session, task, "первый", offset=1)
        second = await _enqueue(db_session, task, "второй", offset=2)
        injector, session = _injector(db_session, task)

        reply = await injector.handle(InjectionAction.INJECT)
        again = await injector.handle(InjectionAction.INJECT)

        assert reply.ok and reply.request_id == str(first.id)
        assert again.ok and again.request_id == str(second.id)
        assert [text for text, _ in session.injected] == ["первый", "второй"]
        assert await _status(db_session, command) is ManualRequestStatus.QUEUED
        assert await _status(db_session, first) is ManualRequestStatus.INJECTED

    async def test_only_commands(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = await _task(db_session)
        await _enqueue(db_session, task, "/review")
        node = Node(
            created_by=task.created_by,
            name="library-node",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="библиотечный промт",
            timeout_seconds=60,
            is_library_item=True,
            max_retries=1,
        )
        db_session.add(node)
        await db_session.flush()
        await _enqueue(
            db_session,
            task,
            None,
            request_type=ManualRequestType.LIBRARY_PROMPT,
            offset=1,
            node_id=node.id,
        )
        injector, session = _injector(db_session, task)

        reply = await injector.handle(InjectionAction.INJECT)

        assert not reply.ok and reply.reason == REASON_NOTHING_TO_INJECT
        assert session.injected == []

    async def test_session_refuses(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "текст")
        injector, session = _injector(db_session, task)
        session.refusal = "no_turn"

        reply = await injector.handle(InjectionAction.INJECT)

        assert not reply.ok and reply.reason == "no_turn"
        assert session.injected == []
        assert await _status(db_session, request) is ManualRequestStatus.QUEUED

    async def test_refusal_is_logged(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        await _enqueue(db_session, task, "текст")
        injector, session = _injector(db_session, task)
        session.refusal = "awaiting_decision"

        with structlog.testing.capture_logs() as logs:
            await injector.handle(InjectionAction.INJECT)

        refused = [entry for entry in logs if entry["event"] == "injection_refused"]
        assert [(e["reason"], e["action"], e["task_id"]) for e in refused] == [
            ("awaiting_decision", "inject", str(task.id)),
        ]

    async def test_session_fails(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "текст")
        injector, session = _injector(db_session, task)
        session.fail_with = RuntimeError("сбой CLI")

        reply = await injector.handle(InjectionAction.INJECT)

        assert not reply.ok and reply.reason == REASON_FAILED and reply.message == "сбой CLI"
        assert await _status(db_session, request) is ManualRequestStatus.QUEUED

    async def test_skips_unpreparable(self, db_session: AsyncSession) -> None:
        """Промт с ошибкой подстановки не закрывает путь остальным."""
        task = await _task(db_session)
        broken = await _enqueue(db_session, task, "Проверь {{task.no_such_field}}", offset=0)
        good = await _enqueue(db_session, task, "нормальный", offset=1)
        injector, session = _injector(db_session, task)

        with structlog.testing.capture_logs() as logs:
            reply = await injector.handle(InjectionAction.INJECT)

        assert reply.ok and reply.request_id == str(good.id)
        skipped = [entry for entry in logs if entry["event"] == "injection_prompt_skipped"]
        assert [entry["request_id"] for entry in skipped] == [str(broken.id)]
        assert "Проверь" not in str(skipped[0])
        assert [text for text, _ in session.injected] == ["нормальный"]
        assert await _status(db_session, broken) is ManualRequestStatus.QUEUED
        assert await _status(db_session, good) is ManualRequestStatus.INJECTED

    async def test_all_unpreparable(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = await _task(db_session)
        broken = await _enqueue(db_session, task, "Проверь {{task.no_such_field}}")
        injector, session = _injector(db_session, task)

        reply = await injector.handle(InjectionAction.INJECT)

        assert not reply.ok and reply.reason == REASON_FAILED
        assert reply.message and "no_such_field" in reply.message
        assert session.injected == []
        assert await _status(db_session, broken) is ManualRequestStatus.QUEUED


class TestObserver:
    """Судьба влитого сообщения."""

    async def test_taken_writes_feed(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "влитый промт")
        injector, _ = _injector(db_session, task)
        await injector.handle(InjectionAction.INJECT)

        await injector.taken(str(request.id))

        assert await _status(db_session, request) is ManualRequestStatus.DONE
        logs = (
            await db_session.scalars(sa.select(NodeLog).where(NodeLog.task_id == task.id))
        ).all()
        assert len(logs) == 1
        assert logs[0].trigger_type is NodeLogTriggerType.FREEFORM_MANUAL
        assert logs[0].status is NodeLogStatus.SUCCESS
        assert logs[0].rendered_prompt == "влитый промт"

    async def test_taken_logs_wait_time(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "влитый")
        injector, _ = _injector(db_session, task)
        await injector.handle(InjectionAction.INJECT)

        with structlog.testing.capture_logs() as logs:
            await injector.taken(str(request.id))

        taken = [entry for entry in logs if entry["event"] == "prompt_injection_taken"]
        assert len(taken) == 1
        assert isinstance(taken[0]["wait_ms"], int) and taken[0]["wait_ms"] >= 0

    async def test_taken_ignores_queued(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "в очереди")
        injector, _ = _injector(db_session, task)

        await injector.taken(str(request.id))

        assert await _status(db_session, request) is ManualRequestStatus.QUEUED
        assert (
            await db_session.scalars(sa.select(NodeLog).where(NodeLog.task_id == task.id))
        ).all() == []

    async def test_returned_to_queue(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "текст")
        injector, _ = _injector(db_session, task)
        await injector.handle(InjectionAction.INJECT)

        await injector.returned(str(request.id))

        assert await _status(db_session, request) is ManualRequestStatus.QUEUED


class TestCancel:
    """Отмена влитого промта."""

    async def test_returns_last(
        self,
        db_session: AsyncSession,
    ) -> None:
        task = await _task(db_session)
        first = await _enqueue(db_session, task, "первый", offset=0)
        second = await _enqueue(db_session, task, "второй", offset=1)
        injector, _ = _injector(db_session, task)
        await injector.handle(InjectionAction.INJECT)
        await injector.handle(InjectionAction.INJECT)

        reply = await injector.handle(InjectionAction.CANCEL)

        assert reply.ok and reply.request_id == str(second.id)
        assert await _status(db_session, second) is ManualRequestStatus.QUEUED
        assert await _status(db_session, first) is ManualRequestStatus.INJECTED
        again = await injector.handle(InjectionAction.CANCEL)
        assert again.ok and again.request_id == str(first.id)

    async def test_too_late(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "текст")
        injector, session = _injector(db_session, task)
        await injector.handle(InjectionAction.INJECT)
        session.cancel_result = False

        reply = await injector.handle(InjectionAction.CANCEL)

        assert not reply.ok and reply.reason == REASON_TOO_LATE
        assert await _status(db_session, request) is ManualRequestStatus.INJECTED

    async def test_nothing_to_cancel(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        injector, _ = _injector(db_session, task)

        reply = await injector.handle(InjectionAction.CANCEL)

        assert not reply.ok and reply.reason == REASON_NOTHING_TO_CANCEL


class TestCleanup:
    """Статусы `injected` вне влития."""

    async def test_return_leftover(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        stuck = await _enqueue(db_session, task, "застрял")
        stuck.status = ManualRequestStatus.INJECTED
        await db_session.flush()

        count = await return_leftover_injections(db_session, task.id)

        assert count == 1
        assert await _status(db_session, stuck) is ManualRequestStatus.QUEUED

    async def test_turn_error_returns(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        injected = await _enqueue(db_session, task, "влитый")
        injected.status = ManualRequestStatus.INJECTED
        processing = await _enqueue(db_session, task, "выполнялся", offset=1)
        processing.status = ManualRequestStatus.PROCESSING
        await db_session.commit()

        await close_turn_after_error(db_session, task_id=task.id, error=RuntimeError("сбой хода"))

        assert await _status(db_session, injected) is ManualRequestStatus.QUEUED
        # Выполнявшийся запрос по-прежнему закрывается, а не возвращается.
        assert await _status(db_session, processing) is ManualRequestStatus.DONE

    async def test_blocks_finishing(self, db_session: AsyncSession) -> None:
        task = await _task(db_session)
        await ensure_manual_requests_drained(db_session, task.id)
        request = await _enqueue(db_session, task, "влитый")
        request.status = ManualRequestStatus.INJECTED
        await db_session.flush()

        with pytest.raises(ConflictError):
            await ensure_manual_requests_drained(db_session, task.id)


class TestCommandChannel:
    """Канал команд API → воркер."""

    async def test_reply_from_worker(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "через Redis")
        injector, session = _injector(db_session, task)
        server = asyncio.create_task(
            serve_injection_commands(redis_client, task.id, injector, poll_seconds=0.01),
        )
        try:
            reply = await send_injection_command(
                redis_client, task.id, InjectionAction.INJECT, wait_seconds=3
            )
        finally:
            server.cancel()

        assert reply == InjectionReply(ok=True, request_id=str(request.id))
        assert session.injected[0][0] == "через Redis"

    async def test_timeout_abandons(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task = await _task(db_session)
        await _enqueue(db_session, task, "текст")
        injector, session = _injector(db_session, task)

        with pytest.raises(InjectionUnavailableError):
            await send_injection_command(
                redis_client, task.id, InjectionAction.INJECT, wait_seconds=0.1
            )
        server = asyncio.create_task(
            serve_injection_commands(redis_client, task.id, injector, poll_seconds=0.01),
        )
        await asyncio.sleep(0.2)
        server.cancel()

        assert session.injected == []

    async def test_drops_stale(self, db_session: AsyncSession, redis_client: Redis) -> None:
        task = await _task(db_session)
        await _enqueue(db_session, task, "текст")
        injector, session = _injector(db_session, task)
        stale = {"id": uuid.uuid4().hex, "action": "inject", "at": time.time() - 3600}
        await redis_client.lpush(f"task:{task.id}:inject:commands", json.dumps(stale))
        with structlog.testing.capture_logs() as logs:
            server = asyncio.create_task(
                serve_injection_commands(redis_client, task.id, injector, poll_seconds=0.01),
            )
            await asyncio.sleep(0.2)
            server.cancel()

        assert session.injected == []
        dropped = [entry for entry in logs if entry["event"] == "injection_command_dropped"]
        # Устаревшая команда — на уровне info, брошенная API — только debug.
        assert [(e["stale"], e["log_level"]) for e in dropped] == [(True, "info")]

    async def test_survives_redis_error(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Сбой Redis не убивает слушателя: после него команды исполняются."""
        task = await _task(db_session)
        request = await _enqueue(db_session, task, "после сбоя")
        injector, session = _injector(db_session, task)
        monkeypatch.setattr(prompt_injection, "_SERVE_ERROR_PAUSE_SECONDS", 0.01)
        real_next = prompt_injection._next_command  # noqa: SLF001
        failures = {"left": 2}

        async def flaky_next(client: Redis, task_id: uuid.UUID) -> dict[str, object] | None:
            if failures["left"] > 0:
                failures["left"] -= 1
                raise ConnectionError("redis недоступен")
            return await real_next(client, task_id)

        monkeypatch.setattr(prompt_injection, "_next_command", flaky_next)
        server = asyncio.create_task(
            serve_injection_commands(redis_client, task.id, injector, poll_seconds=0.01),
        )
        try:
            reply = await send_injection_command(
                redis_client, task.id, InjectionAction.INJECT, wait_seconds=3
            )
        finally:
            server.cancel()

        assert not server.done() or server.cancelled()
        assert reply.ok and reply.request_id == str(request.id)
        assert failures["left"] == 0

    async def test_error_streak_logs_one_stack(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Стек пишется один раз за серию сбоев, дальше — короткие предупреждения."""
        task = await _task(db_session)
        injector, _ = _injector(db_session, task)
        monkeypatch.setattr(prompt_injection, "_SERVE_ERROR_PAUSE_SECONDS", 0.01)

        async def broken_next(client: Redis, task_id: uuid.UUID) -> dict[str, object] | None:
            raise ConnectionError("redis недоступен")

        monkeypatch.setattr(prompt_injection, "_next_command", broken_next)
        with structlog.testing.capture_logs() as logs:
            server = asyncio.create_task(
                serve_injection_commands(redis_client, task.id, injector, poll_seconds=0.01),
            )
            await asyncio.sleep(0.2)
            server.cancel()

        events = [entry["event"] for entry in logs]
        assert events.count("injection_listener_error") == 1
        assert events.count("injection_listener_error_repeated") >= 2
        repeated = next(e for e in logs if e["event"] == "injection_listener_error_repeated")
        assert repeated["error_type"] == "ConnectionError"
