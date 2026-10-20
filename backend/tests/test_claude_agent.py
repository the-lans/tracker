"""Тесты `clients/claude_agent.py` (этап 5 плана реализации).

Реальный `ClaudeSDKClient` требует аутентифицированного `claude` CLI и живой
подпроцесс — недоступно в CI/тестовом окружении. `ClaudeCodeSession`
спроектирован именно для этого: принимает клиент через DI как
`ClaudeAgentClientProtocol`, поэтому тесты подставляют лёгкий фейк.
"""

from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, RateLimitInfo, TextBlock

from clients.claude_agent import (
    REMOTE_CONTROL_EXTRA_ARG,
    ClaudeCodeSession,
    build_claude_agent_options,
)
from tests.fakes import (
    FakeClaudeAgentClient,
    make_rate_limit_event,
    make_result_message,
    make_text_delta,
)


def test_build_claude_agent_options_sets_remote_control_flag_on_first_connect() -> None:
    options = build_claude_agent_options(
        resume_session_id=None,
        cwd="tracker/repos/RR-00001/",
        permission_mode="default",
        mcp_servers={},
        claude_config_dir="/data/llm-accounts/acc-1",
        enable_remote_control=True,
    )

    assert options.resume is None
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


async def test_send_and_collect_text_concatenates_text_blocks() -> None:
    fake = FakeClaudeAgentClient(
        messages_per_query=[
            [
                AssistantMessage(content=[TextBlock(text="Привет, ")], model="claude"),
                AssistantMessage(content=[TextBlock(text="мир!")], model="claude"),
                make_result_message(),
            ],
        ],
    )
    session = ClaudeCodeSession(fake)

    turn = await session.send_and_collect_text("say hi")

    assert turn.text == "Привет, мир!"
    assert turn.is_error is False
    assert turn.session_id == "sess-1"
    assert fake.queries == ["say hi"]


async def test_send_and_collect_text_reports_error_result() -> None:
    fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message(is_error=True)]])
    session = ClaudeCodeSession(fake)

    turn = await session.send_and_collect_text("do something risky")

    assert turn.is_error is True


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
