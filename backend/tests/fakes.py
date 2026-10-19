"""Общие тестовые двойники — не файл с тестами, поэтому не подхватывается pytest
(имя не начинается с ``test_``).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from claude_agent_sdk import Message, ResultMessage


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


class FakeClaudeAgentClient:
    """Двойник `ClaudeAgentClientProtocol` (см. `clients/claude_agent.py`).

    ``messages_per_query`` — список последовательностей сообщений, по одной
    на каждый ожидаемый вызов `query()`, в порядке вызовов.
    """

    def __init__(
        self,
        messages_per_query: list[list[Message]],
        *,
        on_query: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._messages_per_query = messages_per_query
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
        self.concurrent_calls += 1
        self.max_observed_concurrency = max(self.max_observed_concurrency, self.concurrent_calls)
        try:
            while self._stream:
                await asyncio.sleep(self.message_delay_seconds)
                message = self._stream.pop(0)
                yield message
                if isinstance(message, ResultMessage):
                    return
        finally:
            self.concurrent_calls -= 1
