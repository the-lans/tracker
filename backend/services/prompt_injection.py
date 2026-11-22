"""Влитие промта из очереди в идущий ход агента (раздел 7.3 ТЗ).

Свободный промт из очереди можно не ждать до конца хода: кнопка «Влить в
текущий ход» отправляет очередной обычный текстовый промт в сессию прямо сейчас.
CLI покажет его модели на ближайшей границе инструмента, ответ войдёт в вывод
текущего хода (общий `ResultMessage`). Пока агент сообщение не взял, его можно
вернуть («Отменить»).

Сессией владеет только её воркер (правило 16 CLAUDE.md): API кладёт команду в
Redis и ждёт ответ воркера, а исполняет её воркер (`serve_injection_commands`).
Слэш-команды, промты библиотеки и скрипты не вливаются: CLI не вливает команду
в ход, а выполняет её отдельным ходом после него.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from clients.claude_agent import InjectionRefusedError
from db.models.enums import (
    ManualRequestStatus,
    ManualRequestType,
    NodeLogStatus,
    NodeLogTriggerType,
)
from db.models.logs import NodeLog
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services.errors import AppError
from services.manual_queue import render_freeform_prompt
from services.templating import is_slash_command_text

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import ClaudeCodeSession

logger = get_logger("prompt_injection")

# Сколько API ждёт ответ воркера, прежде чем сказать «воркер не отвечает».
REPLY_WAIT_SECONDS = 8.0
# Команда старше этого уже не исполняется: пользователь давно получил отказ.
STALE_COMMAND_SECONDS = 15.0
_KEY_TTL_SECONDS = 60
_SERVE_POLL_SECONDS = 0.25
# Сколько очереди просматривать в поисках подходящего промта.
_QUEUE_SCAN_LIMIT = 100
# Пауза слушателя после сбоя Redis или БД, чтобы не крутиться вхолостую.
_SERVE_ERROR_PAUSE_SECONDS = 2.0

# Причины отказа — машинные, их переводит интерфейс.
REASON_NO_TURN = "no_turn"
REASON_AWAITING_DECISION = "awaiting_decision"
REASON_NOTHING_TO_INJECT = "nothing_to_inject"
REASON_NOTHING_TO_CANCEL = "nothing_to_cancel"
REASON_TOO_LATE = "too_late"
REASON_FAILED = "failed"


class InjectionAction(StrEnum):
    INJECT = "inject"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class InjectionReply:
    ok: bool
    request_id: str | None = None
    reason: str | None = None
    message: str | None = None


class InjectionUnavailableError(RuntimeError):
    """Воркер задачи не ответил вовремя: сессия не идёт или воркер занят."""


def _commands_key(task_id: uuid.UUID) -> str:
    return f"task:{task_id}:inject:commands"


def _reply_key(task_id: uuid.UUID, command_id: str) -> str:
    return f"task:{task_id}:inject:reply:{command_id}"


def _abandoned_key(task_id: uuid.UUID, command_id: str) -> str:
    return f"task:{task_id}:inject:abandoned:{command_id}"


def is_injectable_text(request: TaskManualRequestQueue) -> bool:
    """Обычный свободный текст: команды `/…`, промты библиотеки и пересказы не вливаются."""
    return (
        request.request_type is ManualRequestType.FREEFORM_PROMPT
        and request.command_name is None
        and request.raw_prompt_text is not None
        and not is_slash_command_text(request.raw_prompt_text)
    )


async def send_injection_command(
    redis_client: Redis,
    task_id: uuid.UUID,
    action: InjectionAction,
    *,
    wait_seconds: float | None = None,
) -> InjectionReply:
    """
    API → воркер: кладёт команду и ждёт ответ воркера, не дольше ``wait_seconds``.
    Команда, на которую не дождались, помечается брошенной — её не исполнят позже.
    """
    wait_seconds = REPLY_WAIT_SECONDS if wait_seconds is None else wait_seconds
    command_id = uuid.uuid4().hex
    payload = json.dumps({"id": command_id, "action": action.value, "at": time.time()})
    key = _commands_key(task_id)
    await redis_client.lpush(key, payload)
    await redis_client.expire(key, _KEY_TTL_SECONDS)
    raw = await redis_client.brpop([_reply_key(task_id, command_id)], timeout=wait_seconds)
    if raw is None:
        await redis_client.set(_abandoned_key(task_id, command_id), "1", ex=_KEY_TTL_SECONDS)
        logger.warning("injection_command_unanswered", task_id=str(task_id), action=action.value)
        message = "Воркер задачи не ответил"
        raise InjectionUnavailableError(message)
    value = raw[1]
    data = json.loads(value.decode() if isinstance(value, bytes) else value)
    return InjectionReply(**data)


async def _reply(
    redis_client: Redis,
    task_id: uuid.UUID,
    command_id: str,
    reply: InjectionReply,
) -> None:
    key = _reply_key(task_id, command_id)
    await redis_client.lpush(key, json.dumps(asdict(reply)))
    await redis_client.expire(key, _KEY_TTL_SECONDS)


async def _next_command(redis_client: Redis, task_id: uuid.UUID) -> dict[str, object] | None:
    """Следующая актуальная команда; устаревшие и брошенные отбрасываются без ответа."""
    while True:
        raw = await redis_client.rpop(_commands_key(task_id))
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        command: dict[str, object] = json.loads(text)
        command_id = str(command["id"])
        age = time.time() - float(str(command["at"]))
        if age > STALE_COMMAND_SECONDS or await redis_client.get(
            _abandoned_key(task_id, command_id),
        ):
            logger.info("injection_command_dropped", task_id=str(task_id), age=round(age, 1))
            continue
        return command


class PromptInjector:
    """
    Исполнитель влития на стороне воркера: команды API и судьба влитых сообщений
    (`InjectionObserver` сессии): взято — запись в ленте и `done`, возвращено —
    запрос снова в очереди.
    """

    def __init__(
        self,
        *,
        task_id: uuid.UUID,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self._task_id = task_id
        # Сессия создаётся с этим объектом как наблюдателем и привязывается после.
        self._bound_session: ClaudeCodeSession | None = None
        self._session_factory = session_factory
        # Показываемый текст влитого запроса (секреты замаскированы) — для записи в ленте.
        self._display: dict[uuid.UUID, str] = {}

    def bind(self, session: ClaudeCodeSession) -> None:
        self._bound_session = session

    @property
    def _session(self) -> ClaudeCodeSession:
        assert self._bound_session is not None, "bind() обязателен до первой команды"
        return self._bound_session

    async def handle(self, action: InjectionAction) -> InjectionReply:
        try:
            if action is InjectionAction.INJECT:
                return await self._inject()
            return await self._cancel()
        except Exception as exc:
            logger.exception("injection_command_failed", task_id=str(self._task_id))
            return InjectionReply(ok=False, reason=REASON_FAILED, message=str(exc))

    async def _inject(self) -> InjectionReply:
        refusal = self._session.injection_refusal()
        if refusal is not None:
            return InjectionReply(ok=False, reason=refusal)
        # Промт, который не удалось подготовить (например, неизвестная переменная),
        # пропускается: он не должен закрывать путь остальным.
        skipped: set[uuid.UUID] = set()
        first_error: str | None = None
        async with self._session_factory() as db_session:
            while True:
                request = await _claim_next_injectable(db_session, self._task_id, skipped)
                if request is None:
                    if first_error is not None:
                        return InjectionReply(ok=False, reason=REASON_FAILED, message=first_error)
                    return InjectionReply(ok=False, reason=REASON_NOTHING_TO_INJECT)
                try:
                    task = await db_session.get(Task, self._task_id)
                    assert task is not None
                    assert request.raw_prompt_text is not None
                    prompt = await render_freeform_prompt(
                        db_session,
                        task=task,
                        text=request.raw_prompt_text,
                    )
                    self._display[request.id] = prompt.display
                    await self._session.inject_prompt(prompt.text, str(request.id))
                except InjectionRefusedError as refused:
                    await _release(db_session, request.id)
                    return InjectionReply(ok=False, reason=refused.reason)
                except AppError as error:
                    await _release(db_session, request.id)
                    skipped.add(request.id)
                    first_error = first_error or str(error)
                    continue
                except Exception:
                    await _release(db_session, request.id)
                    raise
                logger.info(
                    "prompt_injected",
                    task_id=str(self._task_id),
                    request_id=str(request.id),
                )
                return InjectionReply(ok=True, request_id=str(request.id))

    async def _cancel(self) -> InjectionReply:
        async with self._session_factory() as db_session:
            request_id = await db_session.scalar(
                sa.select(TaskManualRequestQueue.id)
                .where(
                    TaskManualRequestQueue.task_id == self._task_id,
                    TaskManualRequestQueue.status == ManualRequestStatus.INJECTED,
                )
                .order_by(TaskManualRequestQueue.requested_at.desc())
                .limit(1),
            )
        if request_id is None:
            return InjectionReply(ok=False, reason=REASON_NOTHING_TO_CANCEL)
        if not await self._session.cancel_injection(str(request_id)):
            return InjectionReply(ok=False, reason=REASON_TOO_LATE, request_id=str(request_id))
        await self.returned(str(request_id))
        return InjectionReply(ok=True, request_id=str(request_id))

    # --- InjectionObserver ---

    async def taken(self, message_id: str) -> None:
        """Агент взял сообщение: в ленте появляется запись о нём, запрос выполнен."""
        request_id = uuid.UUID(message_id)
        async with self._session_factory() as db_session:
            request = await db_session.get(TaskManualRequestQueue, request_id)
            if request is None or request.status is not ManualRequestStatus.INJECTED:
                return
            display = self._display.pop(request_id, None)
            if display is None and request.raw_prompt_text is not None:
                task = await db_session.get(Task, self._task_id)
                assert task is not None
                display = (
                    await render_freeform_prompt(
                        db_session, task=task, text=request.raw_prompt_text
                    )
                ).display
            now = datetime.now(UTC)
            db_session.add(
                NodeLog(
                    task_id=self._task_id,
                    trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
                    triggered_by=request.requested_by,
                    rendered_prompt=display,
                    status=NodeLogStatus.SUCCESS,
                    started_at=now,
                    finished_at=now,
                ),
            )
            request.status = ManualRequestStatus.DONE
            request.processed_at = now
            await db_session.commit()
        logger.info("prompt_injection_taken", task_id=str(self._task_id), request_id=message_id)

    async def returned(self, message_id: str) -> None:
        """Сообщение вернулось, не дойдя до агента: запрос снова в очереди."""
        request_id = uuid.UUID(message_id)
        self._display.pop(request_id, None)
        async with self._session_factory() as db_session:
            await _set_status(
                db_session,
                request_id,
                ManualRequestStatus.INJECTED,
                ManualRequestStatus.QUEUED,
            )
        logger.info("prompt_injection_returned", task_id=str(self._task_id), request_id=message_id)


async def _release(db_session: AsyncSession, request_id: uuid.UUID) -> None:
    """Не влитый промт возвращается в очередь на прежнее место."""
    await _set_status(
        db_session,
        request_id,
        ManualRequestStatus.INJECTED,
        ManualRequestStatus.QUEUED,
    )


async def _claim_next_injectable(
    db_session: AsyncSession,
    task_id: uuid.UUID,
    skipped: set[uuid.UUID] | None = None,
) -> TaskManualRequestQueue | None:
    """Ближайший по очереди обычный текстовый промт: `queued` → `injected`; прочие не трогаются."""
    candidates = (
        (
            await db_session.execute(
                sa.select(TaskManualRequestQueue)
                .where(
                    TaskManualRequestQueue.task_id == task_id,
                    TaskManualRequestQueue.status == ManualRequestStatus.QUEUED,
                )
                .order_by(TaskManualRequestQueue.requested_at)
                .limit(_QUEUE_SCAN_LIMIT),
            )
        )
        .scalars()
        .all()
    )
    for candidate in candidates:
        if not is_injectable_text(candidate) or candidate.id in (skipped or ()):
            continue
        claimed = await _set_status(
            db_session,
            candidate.id,
            ManualRequestStatus.QUEUED,
            ManualRequestStatus.INJECTED,
        )
        if claimed:
            await db_session.refresh(candidate)
            return candidate
    return None


async def _set_status(
    db_session: AsyncSession,
    request_id: uuid.UUID,
    from_status: ManualRequestStatus,
    to_status: ManualRequestStatus,
) -> bool:
    """Смена статуса запроса сравнением-и-заменой: два исполнителя не возьмут один запрос."""
    changed = await db_session.scalar(
        sa.update(TaskManualRequestQueue)
        .where(
            TaskManualRequestQueue.id == request_id,
            TaskManualRequestQueue.status == from_status,
        )
        .values(status=to_status)
        .returning(TaskManualRequestQueue.id)
        .execution_options(synchronize_session=False),
    )
    await db_session.commit()
    return changed is not None


async def return_leftover_injections(db_session: AsyncSession, task_id: uuid.UUID) -> int:
    """
    Сессия начинается или закончилась, а в `injected` остались запросы (воркер
    упал, процесс CLI ушёл): они возвращаются в очередь — лучше выполнить промт
    ещё раз, чем потерять.
    """
    returned = await db_session.execute(
        sa.update(TaskManualRequestQueue)
        .where(
            TaskManualRequestQueue.task_id == task_id,
            TaskManualRequestQueue.status == ManualRequestStatus.INJECTED,
        )
        .values(status=ManualRequestStatus.QUEUED)
        .execution_options(synchronize_session=False),
    )
    await db_session.commit()
    return int(getattr(returned, "rowcount", 0) or 0)


async def serve_injection_commands(
    redis_client: Redis,
    task_id: uuid.UUID,
    injector: PromptInjector,
    *,
    poll_seconds: float = _SERVE_POLL_SECONDS,
    on_idle: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """
    Пока сессия задачи жива, исполняет команды влития из Redis. Запускается
    фоновой задачей рядом с ходом модели и отменяется вместе с сессией.
    """
    while True:
        try:
            command = await _next_command(redis_client, task_id)
            if command is None:
                if on_idle is not None:
                    await on_idle()
                await asyncio.sleep(poll_seconds)
                continue
            reply = await injector.handle(InjectionAction(str(command["action"])))
            await _reply(redis_client, task_id, str(command["id"]), reply)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Сбой Redis или БД не должен тихо убить слушателя: влитие продолжит
            # работать, а на выходе из сессии нечего будет перевыбрасывать.
            logger.exception("injection_listener_error", task_id=str(task_id))
            await asyncio.sleep(_SERVE_ERROR_PAUSE_SECONDS)
