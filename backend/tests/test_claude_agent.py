"""Тесты `clients/claude_agent.py` (этап 5 плана реализации).

Реальный `ClaudeSDKClient` требует аутентифицированного `claude` CLI и живой
подпроцесс — недоступно в CI/тестовом окружении. `ClaudeCodeSession`
спроектирован именно для этого: принимает клиент через DI как
`ClaudeAgentClientProtocol`, поэтому тесты подставляют лёгкий фейк.
"""

from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from clients.claude_agent import (
    REMOTE_CONTROL_EXTRA_ARG,
    ClaudeCodeSession,
    build_claude_agent_options,
)
from tests.fakes import FakeClaudeAgentClient, make_result_message


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
