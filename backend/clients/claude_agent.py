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
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    StreamEvent,
    TextBlock,
)

from app_logging.config import get_logger

if TYPE_CHECKING:
    from claude_agent_sdk.types import CanUseTool, McpServerConfig, Message
    from claude_agent_sdk.types import PermissionMode as SdkPermissionMode

logger = get_logger("claude_agent")

REMOTE_CONTROL_EXTRA_ARG = "remote-control"
_CONTENT_BLOCK_DELTA_EVENT = "content_block_delta"
_TEXT_DELTA = "text_delta"

# Получатель фрагментов ответа по мере генерации (раздел 15.2).
TextDeltaHandler = Callable[[str], Awaitable[None]]
# Получатель изменений лимита LLM-аккаунта, о которых сообщает CLI (раздел 16.2).
RateLimitHandler = Callable[[RateLimitInfo], Awaitable[None]]
# Вызывается при прерывании хода до `interrupt()` — чтобы снять то, что ход
# успел начать вне самой сессии (ожидание решения пользователя).
AbortHandler = Callable[[], Awaitable[None]]


class ClaudeAgentClientProtocol(Protocol):
    """Часть интерфейса `ClaudeSDKClient`, которой пользуется `ClaudeCodeSession`."""

    def connect(self) -> Awaitable[None]: ...
    def disconnect(self) -> Awaitable[None]: ...
    def query(self, prompt: str) -> Awaitable[None]: ...
    def receive_response(self) -> AsyncIterator[Message]: ...
    def interrupt(self) -> Awaitable[None]: ...
    def set_permission_mode(self, mode: SdkPermissionMode) -> Awaitable[None]: ...


class LlmAccountMissingError(RuntimeError):
    """Задаче без LLM-аккаунта понадобилась сессия Claude Code (раздел 3.1)."""


class OfflineAgentClient:
    """
    Сессия задачи без LLM-аккаунта (раздел 3.1, решение №19 плана): пайплайн
    из одних скриптов работает, не запуская Claude Code CLI. Обращение к LLM
    сюда не доходит — его отклоняют проверки до запуска
    (`services/task_launch.py`) и постановки ручного запроса; если всё же
    дошло, ход завершается понятной ошибкой.
    """

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def query(self, prompt: str) -> None:  # noqa: ARG002 — интерфейс ClaudeSDKClient
        message = "У задачи нет LLM-аккаунта — выполнять LLM-ноды и промты нечем"
        raise LlmAccountMissingError(message)

    async def receive_response(self) -> AsyncIterator[Message]:
        return
        yield  # pragma: no cover — делает метод асинхронным генератором

    async def interrupt(self) -> None:
        return None

    async def set_permission_mode(self, mode: SdkPermissionMode) -> None:  # noqa: ARG002
        return None


def build_claude_agent_options(
    *,
    resume_session_id: str | None,
    cwd: str,
    permission_mode: str | None,
    mcp_servers: dict[str, McpServerConfig],
    claude_config_dir: str,
    enable_remote_control: bool,
    can_use_tool: CanUseTool | None = None,
    fork_session: bool = False,
    add_dirs: Sequence[str] = (),
) -> ClaudeAgentOptions:
    """Собирает `ClaudeAgentOptions` для сессии задачи (раздел 6.1, 19.5).

    ``enable_remote_control`` обязан быть `True` ТОЛЬКО при первом
    `connect()` задачи (раздел 6.1/6.3, решение №1 плана реализации) —
    после установления моста повторная передача флага при resume не
    требуется. ``claude_config_dir`` — изолированная директория выбранного
    LLM-аккаунта (раздел 19.5), не пересекающаяся с директориями других
    аккаунтов.

    Частичные сообщения включены всегда: ответ показывается в ленте по мере
    генерации (раздел 15.2). ``fork_session`` вместе с ``resume_session_id``
    продолжает чужую историю в новой сессии, не меняя исходную, — так
    пересказывается история родительской задачи. ``add_dirs`` — каталоги вне
    ``cwd``, с которыми сессии можно работать: артефакты задачи (раздел 14.3).
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
        fork_session=fork_session,
        add_dirs=list(add_dirs),
    )

    return ClaudeAgentOptions(
        resume=resume_session_id,
        fork_session=fork_session,
        cwd=cwd,
        permission_mode=permission_mode,  # type: ignore[arg-type]
        mcp_servers=mcp_servers,
        env={"CLAUDE_CONFIG_DIR": claude_config_dir},
        extra_args=extra_args,
        can_use_tool=can_use_tool,
        include_partial_messages=True,
        add_dirs=list(add_dirs),
    )


def _text_delta_of(message: StreamEvent) -> str | None:
    """Фрагмент текста ответа самого агента; события субагентов не показываются."""
    if message.parent_tool_use_id is not None:
        return None
    event = message.event
    if event.get("type") != _CONTENT_BLOCK_DELTA_EVENT:
        return None
    delta = event.get("delta") or {}
    if delta.get("type") != _TEXT_DELTA:
        return None
    text = delta.get("text")
    return text if isinstance(text, str) and text else None


class SessionTurnResult:
    """Результат одного обращения к сессии — текст ответа плюс сырой `ResultMessage`.

    Классификация "временный сбой vs постоянный" (раздел 17.3) — решение
    вызывающего кода (`services/failure_classification.py`), а не этого
    клиента: здесь только добросовестно передаётся то, что вернул SDK, —
    в том числе тип ошибки последнего `AssistantMessage` хода.
    """

    __slots__ = ("assistant_error", "result", "text")

    def __init__(
        self,
        *,
        text: str,
        result: ResultMessage,
        assistant_error: str | None = None,
    ) -> None:
        self.text = text
        self.result = result
        self.assistant_error = assistant_error

    @property
    def is_error(self) -> bool:
        return self.result.is_error

    @property
    def session_id(self) -> str:
        return self.result.session_id


_ABORT_DRAIN_TIMEOUT_SECONDS = 10.0


class ClaudeCodeSession:
    """Владелец единственного клиента активной сессии задачи (раздел 6.1, 6.2)."""

    def __init__(
        self,
        client: ClaudeAgentClientProtocol,
        *,
        on_text_delta: TextDeltaHandler | None = None,
        on_abort: AbortHandler | None = None,
        on_rate_limit: RateLimitHandler | None = None,
    ) -> None:
        self._client = client
        self._on_text_delta = on_text_delta
        self._on_abort = on_abort
        self._on_rate_limit = on_rate_limit
        self._lock = asyncio.Lock()
        self._session_id: str | None = None
        # Ход начат (`query()` отправлен), а его `ResultMessage` ещё не
        # прочитан — только такой ход есть смысл прерывать.
        self._turn_open = False
        # Раздел 6.4: текст хода, полученный к этому моменту, — чтобы при
        # остановке, таймауте или падении CLI он не пропал из `node_logs`.
        self._turn_text_parts: list[str] = []

    def take_partial_turn_text(self) -> str | None:
        """
        Текст прерванного хода (раздел 6.4), полученный до остановки, таймаута
        или падения CLI. Буфер очищается: текст попадает ровно в одну запись.
        """
        text = "".join(self._turn_text_parts) or None
        self._turn_text_parts = []
        return text

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

    async def replace_client(self, client: ClaudeAgentClientProtocol) -> None:
        """
        Пересоздаёт процесс CLI между ходами (раздел 6.5, переподключение моста).

        Новый клиент подключается раньше, чем отключается старый: если
        подключение не удалось, сессия остаётся на прежнем процессе.
        """
        async with self._lock:
            await client.connect()
            previous = self._client
            self._client = client
            # Незавершённый ход (если был) ушёл вместе со старым процессом.
            self._turn_open = False
            try:
                await previous.disconnect()
            except Exception:  # noqa: BLE001 — старый процесс уже не нужен, сбой вторичен
                logger.exception("session_previous_client_disconnect_failed")
            logger.info("session_client_replaced")

    async def interrupt(self) -> None:
        async with self._lock:
            await self._client.interrupt()
            logger.info("session_interrupted")

    async def abort_turn(
        self,
        *,
        drain_timeout_seconds: float = _ABORT_DRAIN_TIMEOUT_SECONDS,
    ) -> None:
        """
        Прерывает ход, чей `send_and_collect_text` уже отменён снаружи
        (таймаут ноды, кнопка «Остановить»).

        После `interrupt()` CLI дописывает в поток итоговый `ResultMessage`
        прерванного хода — если его не вычитать, следующий запрос получит
        чужой ответ вместо своего. Ожидание хвоста ограничено по времени:
        прерывание не должно подвешивать воркер.

        Если хода нет (остановка пришла до отправки запроса или после его
        завершения), прерывать нечего: `interrupt()` простаивающему CLI
        лишь подвесил бы воркер на ожидании хвоста, которого не будет.
        """
        async with self._lock:
            if not self._turn_open:
                logger.info("session_abort_skipped_no_open_turn")
                return
            if self._on_abort is not None:
                await self._on_abort()
            await self._client.interrupt()

            async def drain() -> None:
                async for message in self._client.receive_response():
                    if isinstance(message, ResultMessage):
                        return

            try:
                await asyncio.wait_for(drain(), timeout=drain_timeout_seconds)
            except TimeoutError:
                logger.warning("session_abort_drain_timed_out")
            self._turn_open = False
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
            self._turn_open = True
            try:
                self._turn_text_parts = []
                await self._client.query(prompt)
                text_parts = self._turn_text_parts
                result: ResultMessage | None = None
                assistant_error: str | None = None
                async for message in self._client.receive_response():
                    if isinstance(message, StreamEvent):
                        await self._forward_text_delta(message)
                    if isinstance(message, RateLimitEvent) and self._on_rate_limit is not None:
                        await self._on_rate_limit(message.rate_limit_info)
                    if isinstance(message, AssistantMessage):
                        if message.error is not None:
                            assistant_error = message.error
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text_parts.append(block.text)
                    if isinstance(message, ResultMessage):
                        result = message
            except ClaudeSDKError:
                # Процесс CLI упал посреди хода: хвоста ответа уже не будет, и
                # `abort_turn` не должен ждать его у нового процесса (раздел 17.3).
                # Отмена корутины (остановка, таймаут) флаг не трогает — после
                # неё хвост вычитывает `abort_turn`.
                self._turn_open = False
                raise
            self._turn_open = False
            self._turn_text_parts = []
            if result is None:
                error_message = "Сессия завершила приём сообщений без ResultMessage"
                raise RuntimeError(error_message)
            self._session_id = result.session_id
            logger.info(
                "session_query_finished",
                is_error=result.is_error,
                assistant_error=assistant_error,
                session_id=result.session_id,
            )
            return SessionTurnResult(
                text="".join(text_parts),
                result=result,
                assistant_error=assistant_error,
            )

    async def _forward_text_delta(self, message: StreamEvent) -> None:
        if self._on_text_delta is None:
            return
        text = _text_delta_of(message)
        if text is not None:
            await self._on_text_delta(text)
