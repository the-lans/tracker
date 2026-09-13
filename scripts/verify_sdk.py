"""Минимальная проверка claude-agent-sdk: создаёт сессию ClaudeSDKClient,
отправляет один тестовый промт, печатает ответ, корректно закрывает сессию.

Запуск (из корня репозитория, интерпретатор — backend-venv, где установлен
claude-agent-sdk):
    backend/.venv/bin/python scripts/verify_sdk.py
"""

import asyncio

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
)


async def main() -> None:
    options = ClaudeAgentOptions()

    async with ClaudeSDKClient(options=options) as client:
        await client.query("Ответь словом OK")
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)


if __name__ == "__main__":
    asyncio.run(main())
