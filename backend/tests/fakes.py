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
        if self._on_query is not None:
            await self._on_query()

    async def receive_response(self) -> AsyncIterator[Message]:
        self.concurrent_calls += 1
        self.max_observed_concurrency = max(self.max_observed_concurrency, self.concurrent_calls)
        try:
            messages = self._messages_per_query[len(self.queries) - 1]
            for message in messages:
                await asyncio.sleep(0.01)
                yield message
        finally:
            self.concurrent_calls -= 1
