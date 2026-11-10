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
import dataclasses
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
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

    from db.models.enums import NodeType, ReasoningEffort
    from services.llm_routing import TurnPlan, TurnRoute

logger = get_logger("claude_agent")

REMOTE_CONTROL_EXTRA_ARG = "remote-control"
# Правило 1 CLAUDE.md: ход сессии начинает только запрос трекера. Фоновая
# команда или запланированное пробуждение агента завершаются ходом без
# запроса, и его ответ достался бы следующему запросу трекера.
SEQUENTIAL_TURNS_ENV = {
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_DISABLE_CRON": "1",
}
# Раздел 19.3: коммиты и PR агента — без трейлеров и подписи Claude Code.
# Передаётся флагом `--settings`: он приоритетнее `.claude/settings.json`
# репозитория задачи, и репозиторий не может вернуть подпись.
SESSION_CLI_SETTINGS = json.dumps(
    {"attribution": {"commit": "", "pr": "", "sessionUrl": False}},
)
_CONTENT_BLOCK_START_EVENT = "content_block_start"
_CONTENT_BLOCK_DELTA_EVENT = "content_block_delta"
_TEXT_DELTA = "text_delta"
_TEXT_BLOCK = "text"
# Текстовые блоки хода — отдельные реплики агента (до и после вызова
# инструмента): в ответе они идут абзацами, а не сливаются в одну строку.
TEXT_BLOCK_SEPARATOR = "\n\n"
# Раздел 19.7, «Сжатие контекста»: слэш-команда CLI, уходит буквально (правило 2).
COMPACT_COMMAND = "/compact"

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


class TurnRouter(Protocol):
    """
    Аккаунт хода (раздел 19.7, `services/account_router.py`): маршрут
    выбирается перед каждым ходом, ошибка хода сообщается аккаунту маршрута.
    """

    async def plan_turn(
        self,
        *,
        effort: ReasoningEffort | None,
        node_type: NodeType | None,
        boundary: bool,
        has_history: bool,
    ) -> TurnPlan: ...

    async def finish_compaction(self, plan: TurnPlan, *, succeeded: bool) -> None: ...

    async def report_error(self, route: TurnRoute, assistant_error: str | None) -> bool | None: ...


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
    cli_path: str | None = None,
    cli_env: Mapping[str, str] | None = None,
) -> ClaudeAgentOptions:
    """Собирает `ClaudeAgentOptions` для сессии задачи (раздел 6.1, 19.5).

    ``enable_remote_control`` обязан быть `True` ТОЛЬКО при первом
    `connect()` задачи (раздел 6.1/6.3, решение №1 плана реализации) —
    после установления моста повторная передача флага при resume не
    требуется. ``claude_config_dir`` — конфигурационная директория сессии
    задачи (раздел 6.4): входов в ней нет, к модели CLI обращается через
    `llm-gateway` с токеном сессии из ``cli_env`` (раздел 19.7).

    Частичные сообщения включены всегда: ответ показывается в ленте по мере
    генерации (раздел 15.2). ``fork_session`` вместе с ``resume_session_id``
    продолжает чужую историю в новой сессии, не меняя исходную, — так
    пересказывается история родительской задачи. ``add_dirs`` — каталоги вне
    ``cwd``, с которыми сессии можно работать: артефакты задачи (раздел 14.3).
    ``cli_path`` и ``cli_env`` — обёртка, запускающая CLI в контейнере сессии,
    и её настройки (раздел 19.3, `services/session_container.py`). Фоновые
    задачи и пробуждения CLI выключены всегда (`SEQUENTIAL_TURNS_ENV`), подпись
    Claude Code в коммитах и PR — тоже (`SESSION_CLI_SETTINGS`).
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
        cli_path=cli_path,
    )

    return ClaudeAgentOptions(
        resume=resume_session_id,
        fork_session=fork_session,
        cwd=cwd,
        permission_mode=permission_mode,  # type: ignore[arg-type]
        mcp_servers=mcp_servers,
        env={
            **(cli_env or {}),
            **SEQUENTIAL_TURNS_ENV,
            "CLAUDE_CONFIG_DIR": claude_config_dir,
        },
        cli_path=cli_path,
        extra_args=extra_args,
        can_use_tool=can_use_tool,
        include_partial_messages=True,
        add_dirs=list(add_dirs),
        settings=SESSION_CLI_SETTINGS,
    )


def _join_text_blocks(parts: list[str]) -> str:
    return TEXT_BLOCK_SEPARATOR.join(part for part in parts if part)


def _own_text_blocks(message: AssistantMessage) -> list[str]:
    """
    Текст ответа самого агента: реплики субагентов не входят ни в поток, ни в
    итог хода — иначе место решения в потоке и в ответе разошлось бы (15.2).
    """
    if message.parent_tool_use_id is not None:
        return []
    return [block.text for block in message.content if isinstance(block, TextBlock)]


def _starts_text_block(message: StreamEvent) -> bool:
    """Начало нового текстового блока в ответе самого агента."""
    if message.parent_tool_use_id is not None:
        return False
    event = message.event
    block = event.get("content_block") or {}
    return event.get("type") == _CONTENT_BLOCK_START_EVENT and block.get("type") == _TEXT_BLOCK


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

    __slots__ = ("account_transient", "assistant_error", "result", "route", "text")

    def __init__(
        self,
        *,
        text: str,
        result: ResultMessage,
        assistant_error: str | None = None,
        route: TurnRoute | None = None,
        account_transient: bool | None = None,
    ) -> None:
        self.text = text
        self.result = result
        self.assistant_error = assistant_error
        # Каким аккаунтом выполнен ход и временна ли его ошибка с учётом других
        # аккаунтов автора (раздел 17.3); None — ошибка не про аккаунт.
        self.route = route
        self.account_transient = account_transient

    @property
    def is_error(self) -> bool:
        return self.result.is_error

    @property
    def session_id(self) -> str:
        return self.result.session_id


_ABORT_DRAIN_TIMEOUT_SECONDS = 10.0


class UserWaitClock:
    """
    Раздел 7.3: таймаут ноды ограничивает ожидание ответа LLM, а не решения
    пользователя — время, пока ход ждёт ответа в виджете выбора (9.6), в него
    не входит.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._waited = 0.0
        self._started: float | None = None

    def begin(self) -> None:
        if self._started is None:
            self._started = self._now()

    def end(self) -> None:
        if self._started is not None:
            self._waited += self._now() - self._started
            self._started = None

    def is_waiting(self) -> bool:
        return self._started is not None

    def waited_seconds(self) -> float:
        """Сколько всего ход ждал пользователя, включая идущее сейчас ожидание."""
        current = self._now() - self._started if self._started is not None else 0.0
        return self._waited + current


class ClaudeCodeSession:
    """Владелец единственного клиента активной сессии задачи (раздел 6.1, 6.2)."""

    def __init__(
        self,
        client: ClaudeAgentClientProtocol,
        *,
        on_text_delta: TextDeltaHandler | None = None,
        on_abort: AbortHandler | None = None,
        on_rate_limit: RateLimitHandler | None = None,
        router: TurnRouter | None = None,
    ) -> None:
        self._client = client
        self._on_text_delta = on_text_delta
        self._on_abort = on_abort
        self._on_rate_limit = on_rate_limit
        self._router = router
        # Маршрут последнего хода — и прерванного (таймаут, остановка): им ход
        # выполнялся, он попадает в `node_logs` (раздел 19.7).
        self.turn_route: TurnRoute | None = None
        self._lock = asyncio.Lock()
        self._session_id: str | None = None
        # Ход начат (`query()` отправлен), а его `ResultMessage` ещё не
        # прочитан — только такой ход есть смысл прерывать.
        self._turn_open = False
        # Раздел 6.4: текст хода, полученный к этому моменту, — чтобы при
        # остановке, таймауте или падении CLI он не пропал из `node_logs`.
        self._turn_text_parts: list[str] = []
        # В поток хода уже ушёл текст: следующий текстовый блок отделяется.
        self._turn_streamed_text = False
        self.user_wait_clock = UserWaitClock()

    def take_partial_turn_text(self) -> str | None:
        """
        Текст прерванного хода (раздел 6.4), полученный до остановки, таймаута
        или падения CLI. Буфер очищается: текст попадает ровно в одну запись.
        """
        text = _join_text_blocks(self._turn_text_parts) or None
        self._turn_text_parts = []
        return text

    def turn_text_length(self) -> int:
        """
        Длина ответа текущего хода, полученного к этому моменту, — в тех же
        символах, что и итоговый текст хода (раздел 15.2: место решения
        пользователя в ответе).
        """
        return len(_join_text_blocks(self._turn_text_parts))

    @property
    def session_id(self) -> str | None:
        """`session_id` из последнего `ResultMessage` — None до первого ответа."""
        return self._session_id

    @property
    def _runs_cli(self) -> bool:
        """Задача без LLM-аккаунта работает без процесса CLI — сессии в логах нет."""
        return not isinstance(self._client, OfflineAgentClient)

    async def connect(self) -> None:
        async with self._lock:
            await self._client.connect()
            if self._runs_cli:
                logger.info("session_connected")

    async def disconnect(self) -> None:
        async with self._lock:
            await self._client.disconnect()
            if self._runs_cli:
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

    async def send_and_collect_text(
        self,
        prompt: str,
        *,
        effort: ReasoningEffort | None = None,
        node_type: NodeType | None = None,
        boundary: bool = True,
    ) -> SessionTurnResult:
        """Отправляет промт, дожидается ответа целиком, возвращает итог одним объектом.

        Раздел 6.2: единственная точка обращения к сессии — под мьютексом
        от отправки до получения `ResultMessage`, чтобы никакой другой
        вызов (ручной промт, следующая нода) не начался параллельно.
        Аккаунт хода (раздел 19.7) выбирается под тем же мьютексом до
        отправки и внутри хода не меняется; ``effort`` — уровень рассуждений
        ноды (None — аккаунта), ``node_type`` — тип ноды для выбора аккаунта,
        ``boundary`` — ход начинает ноду, её повтор или ручной запрос: только
        на границе аккаунт меняется со сжатием контекста `/compact`.
        """
        async with self._lock:
            route = await self._route(effort=effort, node_type=node_type, boundary=boundary)
            logger.info("session_query_started", prompt_length=len(prompt))
            self._turn_open = True
            try:
                self._turn_text_parts = []
                self._turn_streamed_text = False
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
                        text_parts.extend(_own_text_blocks(message))
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
            account_transient = None
            if result.is_error and route is not None and self._router is not None:
                account_transient = await self._router.report_error(route, assistant_error)
            return SessionTurnResult(
                text=_join_text_blocks(text_parts),
                result=result,
                assistant_error=assistant_error,
                route=route,
                account_transient=account_transient,
            )

    async def _route(
        self,
        *,
        effort: ReasoningEffort | None,
        node_type: NodeType | None,
        boundary: bool,
    ) -> TurnRoute | None:
        self.turn_route = None
        if self._router is None or not self._runs_cli:
            return None
        plan = await self._router.plan_turn(
            effort=effort,
            node_type=node_type,
            boundary=boundary,
            has_history=self._session_id is not None,
        )
        self.turn_route = plan.route
        if plan.compact_with is not None:
            compacted = await self._compact(plan.compact_with)
            await self._router.finish_compaction(plan, succeeded=compacted)
            self.turn_route = dataclasses.replace(plan.route, context_compacted=compacted)
        return self.turn_route

    async def _compact(self, route: TurnRoute) -> bool:
        """
        Служебный ход `/compact` перед ходом на новом аккаунте (раздел 19.7):
        ответ не транслируется и в `node_logs` не пишется. Ошибка хода
        сообщается аккаунту сжатия, а ход на новом аккаунте всё равно идёт.
        """
        assert self._router is not None
        logger.info("session_compaction_started", account_id=str(route.account_id))
        self._turn_open = True
        self._turn_text_parts = []
        result: ResultMessage | None = None
        assistant_error: str | None = None
        try:
            await self._client.query(COMPACT_COMMAND)
            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage) and message.error is not None:
                    assistant_error = message.error
                if isinstance(message, ResultMessage):
                    result = message
        except ClaudeSDKError:
            self._turn_open = False
            raise
        self._turn_open = False
        if result is None:
            logger.warning("session_compaction_without_result")
            return False
        self._session_id = result.session_id
        if result.is_error:
            logger.warning("session_compaction_failed", assistant_error=assistant_error)
            await self._router.report_error(route, assistant_error)
            return False
        return True

    async def _forward_text_delta(self, message: StreamEvent) -> None:
        if self._on_text_delta is None:
            return
        if _starts_text_block(message) and self._turn_streamed_text:
            await self._on_text_delta(TEXT_BLOCK_SEPARATOR)
            return
        text = _text_delta_of(message)
        if text is not None:
            self._turn_streamed_text = True
            await self._on_text_delta(text)
