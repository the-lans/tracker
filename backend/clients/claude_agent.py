"""Обёртка над Claude Agent SDK для одной сессии задачи (раздел 6 ТЗ).

Модель владения (план реализации, "Архитектурные решения", п. A): один
экземпляр `ClaudeCodeSession` живёт в памяти РОВНО ОДНОГО долгоживущего
Celery-таска на весь активный жизненный цикл сессии задачи — не
пересоздаётся между нодами пайплайна, запусками библиотечных промтов или
свободными промтами. Внутренний `asyncio.Lock` — структурная реализация
раздела 6.2 ("любое обращение к сессии... обязано проходить через единый
внутрипроцессный семафор (mutex) на уровне Celery-задачи"): пока сессию
обслуживает один таск, лок не даёт даже случайно вызвать два метода
параллельно из одной корутины.

`ClaudeCodeSession` принимает уже сконструированный клиент через параметр
конструктора (не создаёт `ClaudeSDKClient` сам) — это даёт тестам
подставлять фейковый клиент, реализующий тот же протокол, без реального
подпроцесса `claude` и без аутентификации.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable
from typing import TYPE_CHECKING, Protocol

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock

from app_logging.config import get_logger

if TYPE_CHECKING:
    from claude_agent_sdk.types import CanUseTool, McpServerConfig, Message
    from claude_agent_sdk.types import PermissionMode as SdkPermissionMode

logger = get_logger("claude_agent")

REMOTE_CONTROL_EXTRA_ARG = "remote-control"


class ClaudeAgentClientProtocol(Protocol):
    """Часть интерфейса `ClaudeSDKClient`, которой пользуется `ClaudeCodeSession`."""

    def connect(self) -> Awaitable[None]: ...
    def disconnect(self) -> Awaitable[None]: ...
    def query(self, prompt: str) -> Awaitable[None]: ...
    def receive_response(self) -> AsyncIterator[Message]: ...
    def interrupt(self) -> Awaitable[None]: ...
    def set_permission_mode(self, mode: SdkPermissionMode) -> Awaitable[None]: ...


def build_claude_agent_options(
    *,
    resume_session_id: str | None,
    cwd: str,
    permission_mode: str | None,
    mcp_servers: dict[str, McpServerConfig],
    claude_config_dir: str,
    enable_remote_control: bool,
    can_use_tool: CanUseTool | None = None,
) -> ClaudeAgentOptions:
    """Собирает `ClaudeAgentOptions` для сессии задачи (раздел 6.1, 19.5).

    ``enable_remote_control`` обязан быть `True` ТОЛЬКО при первом
    `connect()` задачи (раздел 6.1/6.3, решение №1 плана реализации) —
    после установления моста повторная передача флага при resume не
    требуется. ``claude_config_dir`` — изолированная директория выбранного
    LLM-аккаунта (раздел 19.5), не пересекающаяся с директориями других
    аккаунтов.
    """
    extra_args: dict[str, str | None] = {}
    if enable_remote_control:
        extra_args[REMOTE_CONTROL_EXTRA_ARG] = None

    logger.info(
        "claude_agent_options_built",
        resume_session_id=resume_session_id,
        cwd=cwd,
        permission_mode=permission_mode,
        mcp_server_names=sorted(mcp_servers),
        enable_remote_control=enable_remote_control,
        extra_args=extra_args,
    )

    return ClaudeAgentOptions(
        resume=resume_session_id,
        cwd=cwd,
        permission_mode=permission_mode,  # type: ignore[arg-type]
        mcp_servers=mcp_servers,
        env={"CLAUDE_CONFIG_DIR": claude_config_dir},
        extra_args=extra_args,
        can_use_tool=can_use_tool,
    )


class SessionTurnResult:
    """Результат одного обращения к сессии — текст ответа плюс сырой `ResultMessage`.

    Классификация "временный сбой vs постоянный" (раздел 17.3) — решение
    вызывающего кода (оркестратор нод, этап 6), а не этого клиента: здесь
    только добросовестно передаётся то, что вернул SDK.
    """

    __slots__ = ("result", "text")

    def __init__(self, *, text: str, result: ResultMessage) -> None:
        self.text = text
        self.result = result

    @property
    def is_error(self) -> bool:
        return self.result.is_error

    @property
    def session_id(self) -> str:
        return self.result.session_id


_ABORT_DRAIN_TIMEOUT_SECONDS = 10.0


class ClaudeCodeSession:
    """Владелец единственного клиента активной сессии задачи (раздел 6.1, 6.2)."""

    def __init__(self, client: ClaudeAgentClientProtocol) -> None:
        self._client = client
        self._lock = asyncio.Lock()
        self._session_id: str | None = None

    @property
    def session_id(self) -> str | None:
        """`session_id` из последнего `ResultMessage` — None до первого ответа."""
        return self._session_id

    async def connect(self) -> None:
        async with self._lock:
            await self._client.connect()
            logger.info("session_connected")

    async def disconnect(self) -> None:
        async with self._lock:
            await self._client.disconnect()
            logger.info("session_disconnected")

    async def interrupt(self) -> None:
        async with self._lock:
            await self._client.interrupt()
            logger.info("session_interrupted")

    async def abort_turn(
        self,
        *,
        drain_timeout_seconds: float = _ABORT_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        """Прерывает ход, чей `send_and_collect_text` уже отменён снаружи
        (таймаут ноды, кнопка «Остановить»).

        После `interrupt()` CLI дописывает в поток итоговый `ResultMessage`
        прерванного хода — если его не вычитать, следующий запрос получит
        чужой ответ вместо своего. Ожидание хвоста ограничено по времени:
        прерывание не должно подвешивать воркер.
        """
        async with self._lock:
            await self._client.interrupt()

            async def drain() -> None:
                async for message in self._client.receive_response():
                    if isinstance(message, ResultMessage):
                        return

            try:
                await asyncio.wait_for(drain(), timeout=drain_timeout_seconds)
            except TimeoutError:
                logger.warning("session_abort_drain_timed_out")
            logger.info("session_turn_aborted")

    async def set_permission_mode(self, mode: SdkPermissionMode) -> None:
        """Раздел 9.1/9.4: переключение режима разрешений посреди сессии
        (`plan_prompt` включает ``plan`` перед отправкой промта; после
        решения пользователя — режим, выбранный им, раздел 9.4)."""
        async with self._lock:
            await self._client.set_permission_mode(mode)
            logger.info("session_permission_mode_changed", mode=mode)

    async def send_and_collect_text(self, prompt: str) -> SessionTurnResult:
        """Отправляет промт, дожидается ответа целиком, возвращает итог одним объектом.

        Раздел 6.2: единственная точка обращения к сессии — под мьютексом
        от отправки до получения `ResultMessage`, чтобы никакой другой
        вызов (ручной промт, следующая нода) не начался параллельно.
        """
        async with self._lock:
            logger.info("session_query_started", prompt_length=len(prompt))
            await self._client.query(prompt)
            text_parts: list[str] = []
            result: ResultMessage | None = None
            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                if isinstance(message, ResultMessage):
                    result = message
            if result is None:
                error_message = "Сессия завершила приём сообщений без ResultMessage"
                raise RuntimeError(error_message)
            self._session_id = result.session_id
            logger.info(
                "session_query_finished",
                is_error=result.is_error,
                session_id=result.session_id,
            )
            return SessionTurnResult(text="".join(text_parts), result=result)
