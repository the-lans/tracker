"""Тесты `clients/claude_agent.py` (этап 5 плана реализации).

Реальный `ClaudeSDKClient` требует аутентифицированного `claude` CLI и живой
подпроцесс — недоступно в CI/тестовом окружении. `ClaudeCodeSession`
спроектирован именно для этого: принимает клиент через DI как
`ClaudeAgentClientProtocol`, поэтому тесты подставляют лёгкий фейк.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
import structlog
from claude_agent_sdk import AssistantMessage, ProcessError, RateLimitInfo, TextBlock

from clients.claude_agent import (
    REMOTE_CONTROL_EXTRA_ARG,
    ClaudeCodeSession,
    OfflineAgentClient,
    build_claude_agent_options,
)
from tests.fakes import (
    FakeClaudeAgentClient,
    make_assistant_error,
    make_rate_limit_event,
    make_result_message,
    make_text_block_start,
    make_text_delta,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from claude_agent_sdk import Message


def test_build_claude_agent_options_sets_remote_control_flag_on_first_connect() -> None:
    options = build_claude_agent_options(
        resume_session_id=None,
        cwd="tracker/repos/RR-00001/",
        permission_mode="default",
        mcp_servers={},
        claude_config_dir="/data/llm-accounts/acc-1",
        enable_remote_control=True,
        add_dirs=["/data/user-files/RR-00001"],
    )

    assert options.resume is None
    assert options.add_dirs == ["/data/user-files/RR-00001"]
    assert options.extra_args == {REMOTE_CONTROL_EXTRA_ARG: None}
    assert options.env == {"CLAUDE_CONFIG_DIR": "/data/llm-accounts/acc-1"}


def test_build_claude_agent_options_omits_remote_control_flag_on_resume() -> None:
    options = build_claude_agent_options(
        resume_session_id="sess-1",
        cwd="tracker/repos/RR-00001/",
        permission_mode="default",
        mcp_servers={},
        claude_config_dir="/data/llm-accounts/acc-1",
        enable_remote_control=False,
    )

    assert options.resume == "sess-1"
    assert options.extra_args == {}


async def test_connect_disconnect_interrupt_delegate_to_client() -> None:
    fake = FakeClaudeAgentClient(messages_per_query=[])
    session = ClaudeCodeSession(fake)

    await session.connect()
    await session.interrupt()
    await session.disconnect()

    assert fake.connected is True
    assert fake.interrupted is True
    assert fake.disconnected is True


async def test_send_and_collect_text_separates_text_blocks() -> None:
    fake = FakeClaudeAgentClient(
        messages_per_query=[
            [
                AssistantMessage(content=[TextBlock(text="Читаю файлы.")], model="claude"),
                AssistantMessage(content=[TextBlock(text="")], model="claude"),
                AssistantMessage(content=[TextBlock(text="План готов.")], model="claude"),
                make_result_message(),
            ],
        ],
    )
    session = ClaudeCodeSession(fake)

    turn = await session.send_and_collect_text("say hi")

    assert turn.text == "Читаю файлы.\n\nПлан готов."
    assert turn.is_error is False
    assert turn.session_id == "sess-1"
    assert fake.queries == ["say hi"]


async def test_send_and_collect_text_reports_error_result() -> None:
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message(is_error=True)]])
    session = ClaudeCodeSession(fake)

    turn = await session.send_and_collect_text("do something risky")

    assert turn.is_error is True


class TestAssistantError:
    @pytest.mark.parametrize(
        ("messages", "expected"),
        [
            ([make_assistant_error("authentication_failed")], "authentication_failed"),
            (
                [make_assistant_error("rate_limit"), make_assistant_error("billing_error")],
                "billing_error",
            ),
            ([], None),
        ],
        ids=["single", "last_wins", "no_error"],
    )
    async def test_reported(
        self,
        messages: list[AssistantMessage],
        expected: str | None,
    ) -> None:
        """Раздел 17.3: тип ошибки ассистента доходит до классификатора сбоев."""
        fake = FakeClaudeAgentClient(
            messages_per_query=[[*messages, make_result_message(is_error=True)]],
        )
        session = ClaudeCodeSession(fake)

        turn = await session.send_and_collect_text("x")

        assert turn.assistant_error == expected


async def test_send_and_collect_text_raises_without_result_message() -> None:
    fake = FakeClaudeAgentClient(
        messages_per_query=[[AssistantMessage(content=[TextBlock(text="oops")], model="claude")]],
    )
    session = ClaudeCodeSession(fake)

    with pytest.raises(RuntimeError):
        await session.send_and_collect_text("incomplete stream")


async def test_concurrent_calls_are_serialized_by_the_session_lock() -> None:
    fake = FakeClaudeAgentClient(
        messages_per_query=[[make_result_message()], [make_result_message()]],
    )
    session = ClaudeCodeSession(fake)

    await asyncio.gather(
        session.send_and_collect_text("первый"),
        session.send_and_collect_text("второй"),
    )

    assert fake.max_observed_concurrency == 1


async def test_abort_turn_drains_tail_so_next_query_gets_its_own_answer() -> None:
    fake = FakeClaudeAgentClient(
        messages_per_query=[
            [
                AssistantMessage(content=[TextBlock(text="прерванный ответ")], model="claude"),
                make_result_message(session_id="sess-old"),
            ],
            [
                AssistantMessage(content=[TextBlock(text="свежий ответ")], model="claude"),
                make_result_message(session_id="sess-new"),
            ],
        ],
    )
    fake.message_delay_seconds = 0.2
    session = ClaudeCodeSession(fake)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(session.send_and_collect_text("первый"), timeout=0.05)
    await session.abort_turn()
    fake.message_delay_seconds = 0.0
    turn = await session.send_and_collect_text("второй")

    assert fake.interrupted is True
    assert turn.text == "свежий ответ"
    assert turn.session_id == "sess-new"


async def test_abort_turn_gives_up_when_no_tail_arrives() -> None:
    async def hang() -> None:
        await asyncio.sleep(3600)

    fake = FakeClaudeAgentClient(messages_per_query=[], on_query=hang)
    session = ClaudeCodeSession(fake)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(session.send_and_collect_text("зависший"), timeout=0.05)

    await session.abort_turn(drain_timeout_seconds=0.05)

    assert fake.interrupted is True


class TestAbortTurnWithoutOpenTurn:
    """
    Остановка до отправки запроса или после его завершения: `interrupt()`
    простаивающему CLI только подвесил бы воркер на ожидании хвоста.
    """

    @pytest.mark.parametrize("finish_turn_first", [False, True], ids=["before", "after"])
    async def test_does_not_interrupt(self, finish_turn_first: bool) -> None:
        fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
        session = ClaudeCodeSession(fake)
        if finish_turn_first:
            await session.send_and_collect_text("завершённый ход")

        await session.abort_turn(drain_timeout_seconds=5)

        assert fake.interrupted is False


class TestStreamingOptions:
    @pytest.mark.parametrize("fork_session", [False, True])
    def test_partial_messages_and_fork(self, fork_session: bool) -> None:
        options = build_claude_agent_options(
            resume_session_id="sess-parent",
            cwd="tracker/repos/RR-00001/",
            permission_mode="default",
            mcp_servers={},
            claude_config_dir="/data/llm-accounts/acc-1",
            enable_remote_control=False,
            fork_session=fork_session,
        )

        assert options.include_partial_messages is True
        assert options.fork_session is fork_session


class TestSessionLifecycleLogs:
    @pytest.mark.parametrize(
        ("offline", "events"),
        [(False, ["session_connected", "session_disconnected"]), (True, [])],
        ids=["cli", "without_llm_account"],
    )
    async def test_logged_only_with_cli(self, offline: bool, events: list[str]) -> None:
        client = OfflineAgentClient() if offline else FakeClaudeAgentClient(messages_per_query=[])
        session = ClaudeCodeSession(client)

        with structlog.testing.capture_logs() as logs:
            await session.connect()
            await session.disconnect()

        assert [entry["event"] for entry in logs] == events


class TestTurnTextLength:
    async def test_counts_collected_blocks_with_separator(self) -> None:
        lengths: list[int] = []
        fake = FakeClaudeAgentClient(
            messages_per_query=[
                [
                    AssistantMessage(content=[TextBlock(text="Читаю")], model="claude"),
                    AssistantMessage(content=[TextBlock(text="Готово")], model="claude"),
                    make_result_message(),
                ],
            ],
        )
        session = ClaudeCodeSession(fake)
        original = fake.receive_response

        async def spying_receive() -> AsyncIterator[Message]:
            async for message in original():
                yield message
                lengths.append(session.turn_text_length())

        fake.receive_response = spying_receive  # type: ignore[method-assign]

        turn = await session.send_and_collect_text("план")

        assert lengths == [len("Читаю"), len(turn.text), len(turn.text)]
        assert session.turn_text_length() == 0


class TestTextDeltas:
    async def test_forwarded_while_answer_is_collected(self) -> None:
        deltas: list[str] = []

        async def collect(text: str) -> None:
            deltas.append(text)

        fake = FakeClaudeAgentClient(
            messages_per_query=[
                [
                    make_text_delta("При"),
                    make_text_delta("вет"),
                    make_text_delta("субагент", parent_tool_use_id="tool-1"),
                    AssistantMessage(content=[TextBlock(text="Привет")], model="claude"),
                    make_result_message(),
                ],
            ],
        )
        session = ClaudeCodeSession(fake, on_text_delta=collect)

        result = await session.send_and_collect_text("скажи привет")

        assert deltas == ["При", "вет"]
        assert result.text == "Привет"

    @pytest.mark.parametrize(
        ("events", "expected"),
        [
            (["start", "Читаю", "start", "Готово"], ["Читаю", "\n\n", "Готово"]),
            (["start", "Читаю"], ["Читаю"]),
            (["start", "Читаю", "subagent_start", "Готово"], ["Читаю", "Готово"]),
        ],
        ids=["second_block_separated", "first_block_plain", "subagent_block_ignored"],
    )
    async def test_text_blocks_separated_in_stream(
        self,
        events: list[str],
        expected: list[str],
    ) -> None:
        deltas: list[str] = []

        async def collect(text: str) -> None:
            deltas.append(text)

        stream = {
            "start": make_text_block_start,
            "subagent_start": lambda: make_text_block_start(parent_tool_use_id="tool-1"),
        }
        messages = [
            stream[event]() if event in stream else make_text_delta(event) for event in events
        ]
        fake = FakeClaudeAgentClient(messages_per_query=[[*messages, make_result_message()]])
        session = ClaudeCodeSession(fake, on_text_delta=collect)

        await session.send_and_collect_text("план")

        assert deltas == expected


class TestReplaceClient:
    async def test_switches_to_new_process(self) -> None:
        old = FakeClaudeAgentClient(messages_per_query=[])
        new = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
        session = ClaudeCodeSession(old)

        await session.replace_client(new)
        await session.send_and_collect_text("после переподключения")

        assert new.connected is True
        assert old.disconnected is True
        assert new.queries == ["после переподключения"]

    async def test_keeps_old_on_failure(self) -> None:
        class FailingClient(FakeClaudeAgentClient):
            async def connect(self) -> None:
                raise RuntimeError("CLI не запустился")

        old = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
        session = ClaudeCodeSession(old)

        with pytest.raises(RuntimeError):
            await session.replace_client(FailingClient(messages_per_query=[]))
        await session.send_and_collect_text("всё ещё работает")

        assert old.disconnected is False
        assert old.queries == ["всё ещё работает"]


class TestAbortHook:
    async def test_runs_before_interrupt(self) -> None:
        events: list[str] = []

        class RecordingClient(FakeClaudeAgentClient):
            async def interrupt(self) -> None:
                events.append("interrupt")
                await super().interrupt()

        async def on_abort() -> None:
            events.append("abort_hook")

        client = RecordingClient(messages_per_query=[[make_result_message()]])
        client.message_delay_seconds = 30
        session = ClaudeCodeSession(client, on_abort=on_abort)
        turn = asyncio.create_task(session.send_and_collect_text("долгий ход"))
        await asyncio.sleep(0.05)
        turn.cancel()
        client.message_delay_seconds = 0

        await session.abort_turn()

        assert events == ["abort_hook", "interrupt"]


class TestRateLimitHook:
    async def test_events_forwarded(self) -> None:
        received: list[str] = []

        async def on_rate_limit(info: RateLimitInfo) -> None:
            received.append(info.status)

        fake = FakeClaudeAgentClient(
            messages_per_query=[[make_rate_limit_event("rejected"), make_result_message()]],
        )
        session = ClaudeCodeSession(fake, on_rate_limit=on_rate_limit)

        await session.send_and_collect_text("ход")

        assert received == ["rejected"]


class TestCrashedTurn:
    """Раздел 17.3: после падения процесса CLI хода больше нет."""

    async def test_abort_skips_interrupt(self) -> None:
        fake = FakeClaudeAgentClient(
            messages_per_query=[],
            failures_per_query={0: ProcessError("CLI упал", exit_code=1)},
        )
        session = ClaudeCodeSession(fake)

        with pytest.raises(ProcessError):
            await session.send_and_collect_text("x")
        await session.abort_turn(drain_timeout_seconds=5)

        assert fake.interrupted is False

    async def test_replacement_closes_open_turn(self) -> None:
        old = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
        old.message_delay_seconds = 5
        replacement = FakeClaudeAgentClient(messages_per_query=[])
        session = ClaudeCodeSession(old)
        turn = asyncio.ensure_future(session.send_and_collect_text("x"))
        await asyncio.sleep(0.05)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn

        await session.replace_client(replacement)
        await session.abort_turn(drain_timeout_seconds=5)

        assert replacement.interrupted is False
