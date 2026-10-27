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
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import ToolPermissionContext
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import NodeLogStatus, NodeLogTriggerType, PermissionMode, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import User
from services.notifications import NotificationEvent
from services.plan_mode import (
    CUSTOM_ANSWER_OPTION,
    DEFAULT_PLAN_OPTIONS,
    PLAN_ACCEPTED_MESSAGE,
    PLAN_ACCEPTED_TOOL_DENIED,
    PLAN_MODE_WRITE_DENIED,
    TOOL_APPROVAL_ALLOW,
    TOOL_APPROVAL_DENY,
    TOOL_APPROVAL_OPTIONS,
    ActiveNodeContext,
    PlanDecisionOption,
    answer_from_resolution,
    apply_plan_decision,
    build_can_use_tool_callback,
    decide_plan_auto_completion,
    encode_decision,
    parse_decision,
    record_user_decision,
)
from services.task_signal import publish_task_signal
from tests.fakes import patch_plan_mode_signals

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from contextlib import AbstractAsyncContextManager

    from claude_agent_sdk.types import CanUseTool

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

    assert _plan_accepted(result)
    await db_session.refresh(node_log)
    assert node_log.pending_plan_text == "1. Сделать X"
    assert node_log.user_input_text == PlanDecisionOption.ACCEPT_AUTO
    # Без `success` нода `plan_prompt` считает план не принятым (сценарий 21.2 №4).
    assert node_log.status is NodeLogStatus.SUCCESS
    await db_session.refresh(task)
    assert task.current_permission_mode is PermissionMode.ACCEPT_EDITS


async def _review_plan_with_decision(
    db_session: AsyncSession,
    redis_client: Redis,
    decision: str,
) -> tuple[Task, NodeLog, PermissionResultAllow | PermissionResultDeny]:
    """План на ревью; пользователь вскоре выбирает ``decision`` в виджете."""
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
        node_log.user_input_text = decision
        await db_session.commit()
        await publish_task_signal(redis_client, task.id)

    resolver = asyncio.create_task(_resolve_soon())
    try:
        result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)
    finally:
        await resolver
    return task, node_log, result


async def test_callback_marks_awaiting_decision_and_resolves_plan_review(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    task, node_log, result = await _review_plan_with_decision(
        db_session,
        redis_client,
        PlanDecisionOption.ACCEPT_DEFAULT,
    )

    assert _plan_accepted(result)
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
    _, node_log, result = await _review_plan_with_decision(
        db_session,
        redis_client,
        PlanDecisionOption.REVISE,
    )

    assert result.behavior == "deny"
    await db_session.refresh(node_log)
    # "Доработать план" не завершает planning — статус остаётся running (раздел 9.5).
    assert node_log.status is NodeLogStatus.RUNNING


async def test_callback_passes_revise_feedback_text_to_denial_message(
    db_session: AsyncSession,
    redis_client: Redis,
) -> None:
    _, _, result = await _review_plan_with_decision(
        db_session,
        redis_client,
        encode_decision(PlanDecisionOption.REVISE, feedback_text="добавь обработку ошибок"),
    )

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

    assert _plan_accepted(result)


class TestDecisionWait:
    async def test_answer_during_status_change(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Ответ, записанный, пока задача переходит в ожидание и рассылаются
        push-уведомления, будит callback, хотя ожидание ещё не началось.
        """
        task, node_log = await _make_task_with_running_node_log(db_session)
        context = ActiveNodeContext(
            node_log_id=node_log.id,
            task_id=task.id,
            auto_accept_plan=False,
        )
        callback = build_can_use_tool_callback(
            context=context,
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
            decision_wait_timeout_seconds=1.0,
        )

        async def user_answers_during_status_change(*_args: object, **_kwargs: object) -> None:
            await record_user_decision(
                db_session,
                task=task,
                node_log_id=node_log.id,
                option_id=PlanDecisionOption.ACCEPT_DEFAULT,
                feedback_text=None,
                redis_client=redis_client,
            )

        monkeypatch.setattr(
            "services.plan_mode.enter_decision_status",
            user_answers_during_status_change,
        )

        result = await callback("ExitPlanMode", {"plan": "1. Сделать X"}, _TEST_TOOL_CONTEXT)

        assert _plan_accepted(result)


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


def _question(text: str, *labels: str) -> dict[str, object]:
    """Вопрос в формате SDK `AskUserQuestion`."""
    return {
        "question": text,
        "header": "Вопрос",
        "options": [{"label": label, "description": ""} for label in labels],
        "multiSelect": False,
    }


def _answering(
    db_session: AsyncSession,
    node_log: NodeLog,
    resolutions: list[str],
    seen: list[tuple[str | None, object]] | None = None,
) -> Callable[..., Awaitable[bool]]:
    """Подмена ожидания сигнала: пользователь отвечает по очереди."""
    remaining = list(resolutions)

    async def user_answers(*_args: object, **_kwargs: object) -> bool:
        await db_session.refresh(node_log)
        if seen is not None:
            seen.append((node_log.pending_question, node_log.pending_options))
        node_log.user_input_text = remaining.pop(0)
        await db_session.commit()
        return True

    return user_answers


def _callback(
    db_session: AsyncSession,
    task: Task,
    node_log: NodeLog,
    *,
    auto_accept_plan: bool = False,
    plan_mode: bool = False,
) -> CanUseTool:
    return build_can_use_tool_callback(
        context=ActiveNodeContext(
            node_log_id=node_log.id,
            task_id=task.id,
            auto_accept_plan=auto_accept_plan,
            plan_mode=plan_mode,
        ),
        session_factory=_non_closing_session_factory(db_session),
        redis_client=Redis(),
        decision_wait_timeout_seconds=5.0,
    )


class TestAskUserQuestion:
    async def test_questions_asked_one_by_one(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        task, node_log = await _make_task_with_running_node_log(db_session)
        seen: list[tuple[str | None, object]] = []
        patch_plan_mode_signals(
            monkeypatch,
            _answering(
                db_session,
                node_log,
                ["1", encode_decision(CUSTOM_ANSWER_OPTION, feedback_text="Redis")],
                seen,
            ),
        )
        questions = [
            _question("Какую базу?", "main", "dev"),
            _question("Какой кеш?", "нет", "memcached"),
        ]

        result = await _callback(db_session, task, node_log)(
            "AskUserQuestion",
            {"questions": questions},
            _TEST_TOOL_CONTEXT,
        )

        assert isinstance(result, PermissionResultAllow)
        assert result.updated_input == {
            "questions": questions,
            "answers": {"Какую базу?": "dev", "Какой кеш?": "Redis"},
        }
        assert seen == [
            ("Какую базу?", [{"id": "0", "label": "main"}, {"id": "1", "label": "dev"}]),
            ("Какой кеш?", [{"id": "0", "label": "нет"}, {"id": "1", "label": "memcached"}]),
        ]
        await db_session.refresh(node_log)
        # Ответ получен — запись снова выполняется, виджет больше не показывается.
        assert node_log.status is NodeLogStatus.RUNNING
        assert node_log.user_input_text == "Какую базу?: dev\nКакой кеш?: Redis"

    @pytest.mark.parametrize(
        ("resolution", "answer"),
        [
            ("0", "Да"),
            (encode_decision("0", feedback_text="но без миграций"), "Да. но без миграций"),
            (encode_decision(CUSTOM_ANSWER_OPTION, feedback_text="Позже"), "Позже"),
        ],
        ids=["option", "option_with_comment", "custom"],
    )
    def test_answer_from_resolution(self, resolution: str, answer: str) -> None:
        options = [{"id": "0", "label": "Да"}, {"id": "1", "label": "Нет"}]
        assert answer_from_resolution(resolution, options) == answer

    async def test_previous_answer_not_reused(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
    ) -> None:
        """Ответ на прошлый вопрос той же записи не принимается за новый."""
        task, node_log = await _make_task_with_running_node_log(db_session)
        node_log.user_input_text = "0"
        await db_session.flush()
        callback = build_can_use_tool_callback(
            context=ActiveNodeContext(node_log_id=node_log.id, task_id=task.id),
            session_factory=_non_closing_session_factory(db_session),
            redis_client=redis_client,
            decision_wait_timeout_seconds=0.3,
        )

        async def unrelated_signal() -> None:
            await asyncio.sleep(0.1)
            await publish_task_signal(redis_client, task.id)

        signaller = asyncio.create_task(unrelated_signal())
        try:
            result = await callback(
                "AskUserQuestion",
                {"questions": [_question("Ещё?", "Да", "Нет")]},
                _TEST_TOOL_CONTEXT,
            )
        finally:
            await signaller

        assert result.behavior == "deny"

    async def test_without_questions_denied(self, db_session: AsyncSession) -> None:
        task, node_log = await _make_task_with_running_node_log(db_session)

        result = await _callback(db_session, task, node_log)(
            "AskUserQuestion",
            {"questions": []},
            _TEST_TOOL_CONTEXT,
        )

        assert result.behavior == "deny"


class TestOtherTools:
    async def test_writes_denied_in_plan_mode(self, db_session: AsyncSession) -> None:
        """Раздел 9.1: в режиме планирования агент не меняет файлы."""
        task, node_log = await _make_task_with_running_node_log(db_session)

        result = await _callback(db_session, task, node_log, plan_mode=True)(
            "Write",
            {"file_path": "a.py", "content": "x"},
            _TEST_TOOL_CONTEXT,
        )

        assert isinstance(result, PermissionResultDeny)
        assert result.message == PLAN_MODE_WRITE_DENIED

    @pytest.mark.parametrize("mode", [None, PermissionMode.ACCEPT_EDITS], ids=["start", "auto"])
    async def test_autonomous_modes_allow(
        self,
        db_session: AsyncSession,
        mode: PermissionMode | None,
    ) -> None:
        task, node_log = await _make_task_with_running_node_log(db_session)
        task.current_permission_mode = mode
        await db_session.flush()

        result = await _callback(db_session, task, node_log)(
            "Bash",
            {"command": "rm -rf build"},
            _TEST_TOOL_CONTEXT,
        )

        assert result.behavior == "allow"

    @pytest.mark.parametrize(
        ("resolution", "behavior"),
        [(TOOL_APPROVAL_ALLOW, "allow"), (TOOL_APPROVAL_DENY, "deny")],
        ids=["allowed", "denied"],
    )
    async def test_default_mode_asks_user(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        resolution: str,
        behavior: str,
    ) -> None:
        """Раздел 9.3: «подтверждать каждое действие» — через виджет выбора."""
        task, node_log = await _make_task_with_running_node_log(db_session)
        task.current_permission_mode = PermissionMode.DEFAULT
        await db_session.flush()
        seen: list[tuple[str | None, object]] = []
        patch_plan_mode_signals(
            monkeypatch,
            _answering(db_session, node_log, [resolution], seen),
        )

        result = await _callback(db_session, task, node_log)(
            "Bash",
            {"command": "rm -rf build"},
            _TEST_TOOL_CONTEXT,
        )

        assert result.behavior == behavior
        assert seen == [("Агент хочет выполнить Bash: rm -rf build", TOOL_APPROVAL_OPTIONS)]


class TestPlanAcceptanceMode:
    """Раздел 9.3: принятый план завершает ход ноды `plan_prompt` без изменений."""

    @pytest.mark.parametrize(
        ("option", "mode"),
        [
            (PlanDecisionOption.ACCEPT_AUTO, PermissionMode.ACCEPT_EDITS),
            (PlanDecisionOption.ACCEPT_DEFAULT, PermissionMode.DEFAULT),
        ],
        ids=["auto", "confirm_each"],
    )
    async def test_accept_ends_turn(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
        option: str,
        mode: PermissionMode,
    ) -> None:
        task, node_log = await _make_task_with_running_node_log(db_session)
        context = ActiveNodeContext(node_log_id=node_log.id, task_id=task.id, plan_mode=True)
        patch_plan_mode_signals(
            monkeypatch,
            _answering(db_session, node_log, [option]),
        )
        callback = build_can_use_tool_callback(
            context=context,
            session_factory=_non_closing_session_factory(db_session),
            redis_client=Redis(),
        )

        result = await callback("ExitPlanMode", {"plan": "p"}, _TEST_TOOL_CONTEXT)

        assert _plan_accepted(result)
        assert (context.plan_mode, context.plan_accepted) == (False, True)
        await db_session.refresh(task)
        assert task.current_permission_mode is mode

    async def test_auto_accept_ends_turn(self, db_session: AsyncSession) -> None:
        task, node_log = await _make_task_with_running_node_log(db_session)

        result = await _callback(db_session, task, node_log, auto_accept_plan=True, plan_mode=True)(
            "ExitPlanMode",
            {"plan": "p"},
            _TEST_TOOL_CONTEXT,
        )

        assert _plan_accepted(result)
        await db_session.refresh(task)
        assert task.current_permission_mode is PermissionMode.ACCEPT_EDITS

    @pytest.mark.parametrize("tool_name", ["Write", "Bash", "ExitPlanMode"])
    async def test_tools_denied_after_accept(
        self,
        db_session: AsyncSession,
        tool_name: str,
    ) -> None:
        """Ход дописывается без изменений и без ожидания решения: запись плана — `success`."""
        task, node_log = await _make_task_with_running_node_log(db_session)
        task.current_permission_mode = PermissionMode.DEFAULT
        callback = _callback(db_session, task, node_log, auto_accept_plan=True, plan_mode=True)
        await callback("ExitPlanMode", {"plan": "p"}, _TEST_TOOL_CONTEXT)

        result = await callback(tool_name, {"command": "ls"}, _TEST_TOOL_CONTEXT)

        assert isinstance(result, PermissionResultDeny)
        assert (result.message, result.interrupt) == (PLAN_ACCEPTED_TOOL_DENIED, False)
        await db_session.refresh(node_log)
        assert node_log.status is NodeLogStatus.SUCCESS

    def test_activate_resets_acceptance(self) -> None:
        context = ActiveNodeContext(plan_accepted=True)

        context.activate(node_log_id=uuid.uuid4(), task_id=uuid.uuid4())

        assert context.plan_accepted is False


def _plan_accepted(result: object) -> bool:
    return isinstance(result, PermissionResultDeny) and result.message == PLAN_ACCEPTED_MESSAGE


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
                {"questions": [_question("Какую базу?", "main", "dev")]},
                TaskStatus.PAUSED,
                TaskStatus.AWAITING_INPUT,
                "0",
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

        patch_plan_mode_signals(monkeypatch, user_answers)

        result = await callback(tool_name, tool_input, _TEST_TOOL_CONTEXT)

        if tool_name == "ExitPlanMode":
            assert _plan_accepted(result)
        else:
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

        patch_plan_mode_signals(monkeypatch, wait_forever)

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

        result = await callback(
            "AskUserQuestion",
            {"questions": [_question("?", "Да", "Нет")]},
            _TEST_TOOL_CONTEXT,
        )

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

        assert _plan_accepted(result)
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

        patch_plan_mode_signals(monkeypatch, wait_forever)

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
