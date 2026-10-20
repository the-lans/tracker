"""Тесты `services/plan_mode.py` (этап 8 плана реализации: раздел 9 ТЗ).

`can_use_tool` тестируется напрямую как ЛЮБОЙ вызывающий его SDK код бы
делал — с синтетическими ``tool_name``/``tool_input``/``context`` — реальный
`ClaudeSDKClient` для этого не нужен (см. общий подход в
`tests/test_claude_agent.py`).
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from claude_agent_sdk.types import ToolPermissionContext
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeLogStatus, NodeLogTriggerType, PermissionMode, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import User
from services.notifications import NotificationEvent
from services.plan_mode import (
    DEFAULT_PLAN_OPTIONS,
    ActiveNodeContext,
    PlanDecisionOption,
    apply_plan_decision,
    build_can_use_tool_callback,
    decide_plan_auto_completion,
    encode_decision,
    parse_decision,
)
from services.task_signal import publish_task_signal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager

_TEST_TOOL_CONTEXT = ToolPermissionContext()


async def _make_task_with_running_node_log(
    db_session: AsyncSession,
    *,
    status: TaskStatus = TaskStatus.IN_PROGRESS,
) -> tuple[Task, NodeLog]:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        status=status,
    )
    db_session.add(task)
    await db_session.flush()
    node_log = NodeLog(
        task_id=task.id,
        trigger_type=NodeLogTriggerType.PIPELINE,
        status=NodeLogStatus.RUNNING,
    )
    db_session.add(node_log)
    await db_session.flush()
    return task, node_log


def _non_closing_session_factory(
    db_session: AsyncSession,
) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return factory


def test_apply_plan_decision_accept_auto() -> None:
    result = apply_plan_decision(PlanDecisionOption.ACCEPT_AUTO)

    assert result.allow is True
    assert result.updated_permission_mode is PermissionMode.ACCEPT_EDITS


def test_apply_plan_decision_accept_default() -> None:
    result = apply_plan_decision(PlanDecisionOption.ACCEPT_DEFAULT)

    assert result.allow is True
    assert result.updated_permission_mode is PermissionMode.DEFAULT


def test_apply_plan_decision_revise_denies_and_keeps_feedback() -> None:
    result = apply_plan_decision(PlanDecisionOption.REVISE, feedback_text="добавь тесты")

    assert result.allow is False
    assert result.updated_permission_mode is None
    assert result.feedback_text == "добавь тесты"


def test_apply_plan_decision_raises_for_unknown_option() -> None:
    with pytest.raises(ValueError, match="Неизвестный вариант"):
        apply_plan_decision("bogus")


def test_encode_decision_without_feedback_returns_bare_option_id() -> None:
    assert encode_decision(PlanDecisionOption.ACCEPT_DEFAULT) == PlanDecisionOption.ACCEPT_DEFAULT


def test_encode_decode_decision_round_trip_with_feedback() -> None:
    encoded = encode_decision(PlanDecisionOption.REVISE, feedback_text="добавь тесты")

    option_id, feedback_text = parse_decision(encoded)

    assert option_id == PlanDecisionOption.REVISE
    assert feedback_text == "добавь тесты"


def test_parse_decision_without_feedback_returns_none() -> None:
    option_id, feedback_text = parse_decision(PlanDecisionOption.ACCEPT_AUTO)

    assert option_id == PlanDecisionOption.ACCEPT_AUTO
    assert feedback_text is None


def test_decide_plan_auto_completion_returns_none_when_disabled() -> None:
    assert decide_plan_auto_completion(auto_accept_plan=False) is None


def test_decide_plan_auto_completion_returns_decision_when_enabled() -> None:
    result = decide_plan_auto_completion(auto_accept_plan=True)

    assert result is not None
    assert result.allow is True
    assert result.updated_permission_mode is PermissionMode.ACCEPT_EDITS


async def test_callback_allows_uninterecepted_tools_immediately(db_session: AsyncSession) -> None:
    context = ActiveNodeContext()
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=Redis(),  # не используется для неперехватываемых инструментов
    )

    result = await callback("Read", {"path": "x"}, _TEST_TOOL_CONTEXT)

    assert result.behavior == "allow"


async def test_callback_denies_when_no_active_node_context(db_session: AsyncSession) -> None:
    context = ActiveNodeContext()  # node_log_id/task_id не выставлены
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=Redis(),
    )

    result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)

    assert result.behavior == "deny"


async def test_callback_auto_accepts_plan_without_waiting(db_session: AsyncSession) -> None:
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=True)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=Redis(),  # не используется — путь auto_accept не ждёт сигнала
    )

    result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)

    assert result.behavior == "allow"
    await db_session.refresh(node_log)
    assert node_log.pending_plan_text == "1. Сделать X"
    assert node_log.user_input_text == PlanDecisionOption.ACCEPT_AUTO
    await db_session.refresh(task)
    assert task.current_permission_mode is PermissionMode.ACCEPT_EDITS


async def test_callback_marks_awaiting_decision_and_resolves_plan_review(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=False)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=redis_client,
        decision_wait_timeout_seconds=5.0,
    )

    async def _resolve_soon() -> None:
        await asyncio.sleep(0.1)
        node_log.user_input_text = PlanDecisionOption.ACCEPT_DEFAULT
        await db_session.commit()
        await publish_task_signal(redis_client, task.id)

    resolver = asyncio.create_task(_resolve_soon())
    try:
        result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)
    finally:
        await resolver

    assert result.behavior == "allow"
    await db_session.refresh(node_log)
    assert node_log.pending_plan_text == "1. Сделать X"
    assert node_log.pending_options == DEFAULT_PLAN_OPTIONS
    assert node_log.status is NodeLogStatus.SUCCESS
    await db_session.refresh(task)
    # ACCEPT_DEFAULT (раздел 9.3): "подтверждать каждое действие" -> default.
    assert task.current_permission_mode is PermissionMode.DEFAULT


async def test_callback_denies_when_revise_chosen(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=False)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=redis_client,
        decision_wait_timeout_seconds=5.0,
    )

    async def _resolve_soon() -> None:
        await asyncio.sleep(0.1)
        node_log.user_input_text = PlanDecisionOption.REVISE
        await db_session.commit()
        await publish_task_signal(redis_client, task.id)

    resolver = asyncio.create_task(_resolve_soon())
    try:
        result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)
    finally:
        await resolver

    assert result.behavior == "deny"
    await db_session.refresh(node_log)
    # "Доработать план" не завершает planning — статус остаётся running (раздел 9.5).
    assert node_log.status is NodeLogStatus.RUNNING


async def test_callback_passes_revise_feedback_text_to_denial_message(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=False)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=redis_client,
        decision_wait_timeout_seconds=5.0,
    )

    async def _resolve_soon() -> None:
        await asyncio.sleep(0.1)
        node_log.user_input_text = encode_decision(
            PlanDecisionOption.REVISE,
            feedback_text="добавь обработку ошибок",
        )
        await db_session.commit()
        await publish_task_signal(redis_client, task.id)

    resolver = asyncio.create_task(_resolve_soon())
    try:
        result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)
    finally:
        await resolver

    assert result.behavior == "deny"
    assert result.message == "добавь обработку ошибок"


async def test_unrelated_task_signal_does_not_reject_pending_plan(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    """Свободный промт, поставленный в очередь во время ревью плана, будит
    тот же канал задачи — план от этого не должен отклоняться."""
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=False)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=redis_client,
        decision_wait_timeout_seconds=5.0,
    )

    async def _queue_prompt_then_decide() -> None:
        await asyncio.sleep(0.1)
        await publish_task_signal(redis_client, task.id)
        await asyncio.sleep(0.2)
        node_log.user_input_text = PlanDecisionOption.ACCEPT_DEFAULT
        await db_session.commit()
        await publish_task_signal(redis_client, task.id)

    resolver = asyncio.create_task(_queue_prompt_then_decide())
    try:
        result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)
    finally:
        await resolver

    assert result.behavior == "allow"


async def test_callback_denies_on_timeout_without_resolution(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=False)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=redis_client,
        decision_wait_timeout_seconds=0.2,
    )

    result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)

    assert result.behavior == "deny"


async def test_callback_handles_ask_user_question_and_returns_answer(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=False)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=redis_client,
        decision_wait_timeout_seconds=5.0,
    )
    tool_input = {
        "question": "Продолжать с миграцией?",
        "options": [{"id": "yes", "label": "Да"}, {"id": "no", "label": "Нет"}],
    }

    async def _resolve_soon() -> None:
        await asyncio.sleep(0.1)
        node_log.user_input_text = "yes"
        await db_session.commit()
        await publish_task_signal(redis_client, task.id)

    resolver = asyncio.create_task(_resolve_soon())
    try:
        result = await callback("AskUserQuestion", tool_input, _TEST_TOOL_CONTEXT)
    finally:
        await resolver

    assert result.behavior == "allow"
    assert result.updated_input is not None
    assert result.updated_input["answer"] == "yes"
    await db_session.refresh(node_log)
    assert node_log.pending_question == "Продолжать с миграцией?"
    assert node_log.pending_options == [
        {"id": "yes", "label": "Да"},
        {"id": "no", "label": "Нет"},
    ]


async def test_callback_handles_ask_user_question_with_plain_string_options(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task, node_log = await _make_task_with_running_node_log(db_session)
    context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, auto_accept_plan=False)
    callback = build_can_use_tool_callback(
        context=context,
        session_factory=_non_closing_session_factory(db_session),
        redis_client=redis_client,
        decision_wait_timeout_seconds=5.0,
    )
    tool_input = {"question": "Продолжать?", "options": ["Да", "Нет"]}

    async def _resolve_soon() -> None:
        await asyncio.sleep(0.1)
        node_log.user_input_text = "0"
        await db_session.commit()
        await publish_task_signal(redis_client, task.id)

    resolver = asyncio.create_task(_resolve_soon())
    try:
        await callback("AskUserQuestion", tool_input, _TEST_TOOL_CONTEXT)
    finally:
        await resolver

    await db_session.refresh(node_log)
    assert node_log.pending_options == [
        {"id": "0", "label": "Да"},
        {"id": "1", "label": "Нет"},
    ]


async def _status_of(db_session: AsyncSession, task: Task) -> TaskStatus:
    await db_session.refresh(task)
    return task.status


class TestDecisionStatus:
    """Раздел 14.3: на время ожидания решения — статус ожидания, затем возврат."""

    @pytest.mark.parametrize(
        ("tool_name", "tool_input", "start_status", "awaiting_status", "answer"),
        [
            (
                "ExitPlanMode",
                {"plan": "1. Сделать X"},
                TaskStatus.IN_PROGRESS,
                TaskStatus.PLAN_REVIEW,
                PlanDecisionOption.ACCEPT_DEFAULT,
            ),
            (
                "AskUserQuestion",
                {"question": "Какую базу?", "options": ["main", "dev"]},
                TaskStatus.PAUSED,
                TaskStatus.AWAITING_INPUT,
                "main",
            ),
        ],
        ids=["plan_from_in_progress", "question_from_paused"],
    )
    async def test_round_trip(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
        tool_name: str,
        tool_input: dict[str, object],
        start_status: TaskStatus,
        awaiting_status: TaskStatus,
        answer: str,
    ) -> None:
        events: list[NotificationEvent] = []

        async def capture_notification(
            _db: AsyncSession,
            *,
            event: NotificationEvent,
            **_: object,
        ) -> None:
            events.append(event)

        monkeypatch.setattr("services.task_status.notify_task_event", capture_notification)
        task, node_log = await _make_task_with_running_node_log(db_session, status=start_status)
        callback = build_can_use_tool_callback(
            context=ActiveNodeContext(node_log_id=node_log.id, task_id=task.id),
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
            decision_wait_timeout_seconds=5.0,
        )

        statuses_while_waiting: list[TaskStatus] = []

        async def user_answers(*_args: object, **_kwargs: object) -> bool:
            # Ожидание сигнала начинается только после перехода в ожидание.
            statuses_while_waiting.append(await _status_of(db_session, task))
            node_log.user_input_text = answer
            await db_session.commit()
            return True

        monkeypatch.setattr("services.plan_mode.wait_for_task_signal", user_answers)

        result = await callback(tool_name, tool_input, _TEST_TOOL_CONTEXT)

        assert result.behavior == "allow"
        assert statuses_while_waiting == [awaiting_status]
        assert await _status_of(db_session, task) is start_status
        assert events == [NotificationEvent.AWAITING_DECISION]

    async def test_cancelled_wait_restores_status(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Таймаут ноды или «Остановить» отменяют ход, пока ждётся решение."""
        task, node_log = await _make_task_with_running_node_log(db_session)
        callback = build_can_use_tool_callback(
            context=ActiveNodeContext(node_log_id=node_log.id, task_id=task.id),
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
        )
        waiting_started = asyncio.Event()

        async def wait_forever(*_args: object, **_kwargs: object) -> bool:
            waiting_started.set()
            await asyncio.Event().wait()
            return False

        monkeypatch.setattr("services.plan_mode.wait_for_task_signal", wait_forever)

        async def agent_exits_plan_mode() -> object:
            return await callback("ExitPlanMode", {"plan": "p"}, _TEST_TOOL_CONTEXT)

        waiting = asyncio.create_task(agent_exits_plan_mode())
        await asyncio.wait_for(waiting_started.wait(), timeout=5)
        assert await _status_of(db_session, task) is TaskStatus.PLAN_REVIEW
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        assert await _status_of(db_session, task) is TaskStatus.IN_PROGRESS

    async def test_rebase_conflict_kept(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task, node_log = await _make_task_with_running_node_log(
            db_session,
            status=TaskStatus.REBASE_CONFLICT,
        )
        callback = build_can_use_tool_callback(
            context=ActiveNodeContext(node_log_id=node_log.id, task_id=task.id),
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
            decision_wait_timeout_seconds=0.2,
        )

        result = await callback("AskUserQuestion", {"question": "?"}, _TEST_TOOL_CONTEXT)

        assert result.behavior == "deny"
        assert await _status_of(db_session, task) is TaskStatus.REBASE_CONFLICT

    async def test_auto_accept_keeps_status(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        task, node_log = await _make_task_with_running_node_log(db_session)
        callback = build_can_use_tool_callback(
            context=ActiveNodeContext(
                node_log_id=node_log.id,
                task_id=task.id,
                auto_accept_plan=True,
            ),
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
        )

        result = await callback("ExitPlanMode", {"plan": "p"}, _TEST_TOOL_CONTEXT)

        assert result.behavior == "allow"
        assert await _status_of(db_session, task) is TaskStatus.IN_PROGRESS


class TestCancelDecisionWait:
    async def test_restores_status_before_returning(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Воркер прерывает ход (таймаут ноды): ожидание в задаче-обработчике
        SDK снимается, и статус возвращён к моменту, когда воркер продолжит.
        """
        task, node_log = await _make_task_with_running_node_log(db_session)
        context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id)
        callback = build_can_use_tool_callback(
            context=context,
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
        )
        waiting_started = asyncio.Event()

        async def wait_forever(*_args: object, **_kwargs: object) -> bool:
            waiting_started.set()
            await asyncio.Event().wait()
            return False

        monkeypatch.setattr("services.plan_mode.wait_for_task_signal", wait_forever)

        async def sdk_handler() -> object:
            return await callback("ExitPlanMode", {"plan": "p"}, _TEST_TOOL_CONTEXT)

        handler = asyncio.create_task(sdk_handler())
        await asyncio.wait_for(waiting_started.wait(), timeout=5)

        await context.cancel_decision_wait()

        assert handler.cancelled()
        assert await _status_of(db_session, task) is TaskStatus.IN_PROGRESS

    async def test_nothing_to_cancel(self) -> None:
        await ActiveNodeContext().cancel_decision_wait()

    async def test_cancel_during_status_change(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ход прерван, пока после перехода в `plan_review` отправляется
        уведомление, — ожидание ещё не началось, но статус всё равно возвращён."""
        task, node_log = await _make_task_with_running_node_log(db_session)
        context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id)
        callback = build_can_use_tool_callback(
            context=context,
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
        )
        notifying = asyncio.Event()

        async def slow_notification(*_args: object, **_kwargs: object) -> None:
            notifying.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("services.task_status.notify_task_event", slow_notification)

        async def sdk_handler() -> object:
            return await callback("ExitPlanMode", {"plan": "p"}, _TEST_TOOL_CONTEXT)

        handler = asyncio.create_task(sdk_handler())
        await asyncio.wait_for(notifying.wait(), timeout=5)
        monkeypatch.undo()

        await context.cancel_decision_wait()

        assert handler.cancelled()
        assert await _status_of(db_session, task) is TaskStatus.IN_PROGRESS
