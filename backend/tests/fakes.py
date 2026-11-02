"""Общие тестовые двойники — не файл с тестами, поэтому не подхватывается pytest
(имя не начинается с ``test_``).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING

from claude_agent_sdk import (
    AssistantMessage,
    Message,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    StreamEvent,
    TextBlock,
)
from claude_agent_sdk.types import AssistantMessageError, RateLimitStatus

from db.models.enums import NodeType, ReasoningEffort
from services.llm_routing import NoLlmAccountAvailableError, TurnRoute

if TYPE_CHECKING:
    import pytest


def make_result_message(*, is_error: bool = False, session_id: str = "sess-1") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=100,
        duration_api_ms=80,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        result="итоговый результат" if not is_error else None,
    )


def make_assistant_error(error: AssistantMessageError, text: str = "") -> AssistantMessage:
    """Сообщение ассистента с типом ошибки, как его присылает CLI (раздел 17.3)."""
    return AssistantMessage(content=[TextBlock(text=text)], model="claude", error=error)


def make_text_delta(text: str, *, parent_tool_use_id: str | None = None) -> StreamEvent:
    """Частичное сообщение SDK (`include_partial_messages`) с фрагментом текста."""
    return StreamEvent(
        uuid="evt",
        session_id="sess-1",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
        parent_tool_use_id=parent_tool_use_id,
    )


def make_text_block_start(*, parent_tool_use_id: str | None = None) -> StreamEvent:
    """Частичное сообщение SDK: начало нового текстового блока ответа."""
    return StreamEvent(
        uuid="evt",
        session_id="sess-1",
        event={"type": "content_block_start", "content_block": {"type": "text", "text": ""}},
        parent_tool_use_id=parent_tool_use_id,
    )


def make_rate_limit_event(
    status: RateLimitStatus,
    *,
    resets_at: int | None = None,
) -> RateLimitEvent:
    """Событие лимита, которое CLI присылает в поток сессии."""
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(status=status, resets_at=resets_at),
        uuid="rl",
        session_id="sess-1",
    )


class FakeClaudeAgentClient:
    """Двойник `ClaudeAgentClientProtocol` (см. `clients/claude_agent.py`).

    ``messages_per_query`` — список последовательностей сообщений, по одной
    на каждый ожидаемый вызов `query()`, в порядке вызовов.
    ``failures_per_query`` — исключение, которым «падает процесс CLI» при
    чтении ответа на вызов `query()` с данным номером (с нуля);
    ``failures_mid_turn`` — то же, но после уже отданной части ответа, вместо
    `ResultMessage`.
    """

    def __init__(
        self,
        messages_per_query: list[list[Message]],
        *,
        on_query: Callable[[], Awaitable[None]] | None = None,
        failures_per_query: dict[int, Exception] | None = None,
        failures_mid_turn: dict[int, Exception] | None = None,
    ) -> None:
        self._messages_per_query = messages_per_query
        self._failures_per_query = failures_per_query or {}
        self._failures_mid_turn = failures_mid_turn or {}
        # Симулирует побочный эффект callback'а разрешений SDK (раздел 9.6),
        # который в реальности мутирует БД ВНУТРИ обработки одного query() —
        # используется тестами `plan_prompt` (см. `test_nodes_dispatch.py`).
        self._on_query = on_query
        self.connected = False
        self.disconnected = False
        self.interrupted = False
        self.queries: list[str] = []
        self.concurrent_calls = 0
        self.max_observed_concurrency = 0
        self.permission_modes: list[str] = []
        self.message_delay_seconds = 0.01
        self._stream: list[Message] = []

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def interrupt(self) -> None:
        self.interrupted = True

    async def set_permission_mode(self, mode: str) -> None:
        self.permission_modes.append(mode)

    async def query(self, prompt: str) -> None:
        self.queries.append(prompt)
        index = len(self.queries) - 1
        if index < len(self._messages_per_query):
            self._stream.extend(self._messages_per_query[index])
        if self._on_query is not None:
            await self._on_query()

    async def receive_response(self) -> AsyncIterator[Message]:
        """Как в SDK: читает общий поток сообщений до первого `ResultMessage`.

        Недочитанный хвост прерванного хода остаётся в потоке и достанется
        следующему чтению — ровно та ситуация, ради которой существует
        `ClaudeCodeSession.abort_turn`.
        """
        failure = self._failures_per_query.get(len(self.queries) - 1)
        if failure is not None:
            raise failure
        self.concurrent_calls += 1
        self.max_observed_concurrency = max(self.max_observed_concurrency, self.concurrent_calls)
        try:
            mid_turn_failure = self._failures_mid_turn.get(len(self.queries) - 1)
            while self._stream:
                await asyncio.sleep(self.message_delay_seconds)
                if mid_turn_failure is not None and isinstance(self._stream[0], ResultMessage):
                    raise mid_turn_failure
                message = self._stream.pop(0)
                yield message
                if isinstance(message, ResultMessage):
                    return
        finally:
            self.concurrent_calls -= 1


def patch_plan_mode_signals(
    monkeypatch: pytest.MonkeyPatch,
    wait: Callable[..., Awaitable[bool]],
) -> None:
    """
    Подмена подписки `services.plan_mode` на сигналы задачи: каждое ожидание
    сигнала — вызов ``wait`` (ход пользователя в тесте).
    """

    @asynccontextmanager
    async def signals(*_args: object, **_kwargs: object) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(wait=wait)

    monkeypatch.setattr("services.plan_mode.subscribe_task_signal", signals)


FAKE_ROUTE = TurnRoute(
    account_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
    prefix="acc-000000000001",
    model="claude-opus-5-5",
    effort=ReasoningEffort.HIGH,
    provider_effort=ReasoningEffort.HIGH,
)


class FakeTurnRouter:
    """
    Двойник `TurnRouter` (`services/account_router.py`): всегда один маршрут;
    ``available=False`` — у автора нет ни одного `active` аккаунта.
    """

    def __init__(
        self,
        route: TurnRoute = FAKE_ROUTE,
        *,
        transient: bool | None = None,
        available: bool = True,
    ) -> None:
        self.route_value = route
        self.transient = transient
        self.available = available
        self.routed: list[tuple[ReasoningEffort | None, NodeType | None]] = []
        self.errors: list[tuple[TurnRoute, str | None]] = []

    async def route(
        self,
        *,
        effort: ReasoningEffort | None,
        node_type: NodeType | None,
    ) -> TurnRoute:
        self.routed.append((effort, node_type))
        if not self.available:
            raise NoLlmAccountAvailableError
        return self.route_value

    async def report_error(self, route: TurnRoute, assistant_error: str | None) -> bool | None:
        self.errors.append((route, assistant_error))
        return self.transient
