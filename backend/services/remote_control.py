"""Мониторинг моста `/remote-control` (раздел 6.5, 6.6 ТЗ), упрощено по решению №1
плана реализации: у `ClaudeSDKClient` нет программного способа узнать статус
моста или переподключить его посреди сессии (см. `docs/remote_control_findings.md`),
поэтому "проверка живости моста" здесь по факту — проверка живости самого
процесса/сессии, обслуживающей задачу.

Полноценная периодическая задача `check_remote_control_bridges` появляется
вместе с реестром активных сессий оркестратора (этап 6) и его регистрацией
в Celery Beat (этап 11) — этот модуль уже сейчас реализует ЧИСТУЮ логику
решения "жив ли процесс -> что делать дальше", не зависящую от конкретного
способа проверки живости.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app_logging.config import bind_task_context, get_logger
from db.models.enums import RemoteControlStatus
from db.models.tasks import Task
from services.errors import ConflictError
from services.maintenance_tasks import find_tasks_requiring_remote_control_check
from services.notifications import NotificationEvent, notify_task_event
from services.session_heartbeat import is_session_alive
from services.task_control import request_bridge_reconnect
from services.task_status import SESSION_ACTIVE_STATUSES, fail_task_after_error

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("remote_control")

MAX_RECONNECT_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class BridgeCheckDecision:
    should_attempt_reconnect: bool
    new_status: RemoteControlStatus | None  # None — статус не меняется


def decide_remote_control_bridge_action(
    *,
    is_process_alive: bool,
    current_reconnect_attempts: int,
) -> BridgeCheckDecision:
    """Раздел 6.6: до двух автоматических попыток восстановления с задержкой;
    после исчерпания — `disconnected` и уведомление (уведомление — забота
    вызывающего кода, этап 14).
    """
    if is_process_alive:
        return BridgeCheckDecision(should_attempt_reconnect=False, new_status=None)
    if current_reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
        return BridgeCheckDecision(
            should_attempt_reconnect=True,
            new_status=RemoteControlStatus.RECONNECTING,
        )
    return BridgeCheckDecision(
        should_attempt_reconnect=False,
        new_status=RemoteControlStatus.DISCONNECTED,
    )


async def record_bridge_status(
    db_session: AsyncSession,
    *,
    task: Task,
    status: RemoteControlStatus,
) -> None:
    """
    Раздел 6.5, 6.6: best-effort статус моста после попытки его установить.

    Решение №1 плана: достоверно узнать состояние моста SDK не позволяет —
    `connected` означает лишь, что процесс CLI с флагом `--remote-control`
    поднялся.
    """
    task.remote_control_status = status
    task.remote_control_last_check_at = datetime.now(UTC)
    if status is RemoteControlStatus.CONNECTED:
        task.remote_control_reconnect_attempts = 0
    await db_session.commit()
    logger.info("remote_control_status_recorded", task_id=str(task.id), status=status.value)


async def start_bridge_reconnect(
    db_session: AsyncSession,
    *,
    task: Task,
    redis_client: Redis,
) -> None:
    """
    Раздел 6.5: новая попытка поднять мост `/remote-control`.

    Сессией владеет воркер — он пересоздаст процесс CLI между ходами и
    обновит статус; здесь лишь фиксируется намерение.
    """
    if task.status not in SESSION_ACTIVE_STATUSES:
        raise ConflictError("У задачи нет активной сессии")
    if task.llm_account_id is None:
        raise ConflictError("У задачи без LLM-аккаунта нет сессии Claude Code")
    task.remote_control_status = RemoteControlStatus.RECONNECTING
    await db_session.commit()
    await request_bridge_reconnect(redis_client, task.id)


class SessionLostError(RuntimeError):
    """Воркер, державший сессию задачи, перестал подавать пульс (раздел 6.6, 17.3)."""


async def _attempt_reconnect(db_session: AsyncSession, *, task: Task, redis_client: Redis) -> None:
    """
    Попытка восстановления: у задачи с LLM-аккаунтом — запрос переподключения
    моста воркеру и статус `reconnecting`; у задачи без аккаунта моста нет,
    засчитывается только попытка.
    """
    task.remote_control_reconnect_attempts += 1
    has_bridge = task.llm_account_id is not None
    if has_bridge:
        task.remote_control_status = RemoteControlStatus.RECONNECTING
    await db_session.commit()
    if has_bridge:
        await request_bridge_reconnect(redis_client, task.id)
    logger.info(
        "remote_control_reconnect_attempted",
        task_id=str(task.id),
        attempt=task.remote_control_reconnect_attempts,
    )


async def _report_bridge_disconnected(db_session: AsyncSession, *, task: Task) -> None:
    """`disconnected` и уведомление (раздел 18.2) — один раз, а не на каждой проверке."""
    already_reported = task.remote_control_status is RemoteControlStatus.DISCONNECTED
    task.remote_control_status = RemoteControlStatus.DISCONNECTED
    await db_session.commit()
    if not already_reported:
        await notify_task_event(
            db_session,
            event=NotificationEvent.REMOTE_CONTROL_DISCONNECTED,
            task=task,
        )


async def _fail_lost_session(db_session: AsyncSession, *, task: Task) -> None:
    """Раздел 6.6, 17.3: сессию больше никто не держит — задача в `failed`, как при её ошибке."""
    task_id = task.id
    logger.warning("session_lost", task_id=str(task_id))
    await fail_task_after_error(
        db_session,
        task_id=task_id,
        error=SessionLostError("воркер сессии перестал отвечать"),
    )


async def check_task_bridge(db_session: AsyncSession, *, task: Task, redis_client: Redis) -> None:
    """
    Раздел 6.6: одна проверка задачи, у которой должна быть живая сессия.

    Живость — пульс воркера (`services/session_heartbeat.py`). Пульса нет —
    до `MAX_RECONNECT_ATTEMPTS` попыток восстановления; после них мост
    `disconnected`, а задача переходит в `failed`.
    """
    alive = await is_session_alive(redis_client, task.id)
    decision = decide_remote_control_bridge_action(
        is_process_alive=alive,
        current_reconnect_attempts=task.remote_control_reconnect_attempts,
    )
    task.remote_control_last_check_at = datetime.now(UTC)
    if alive:
        task.remote_control_reconnect_attempts = 0
        await db_session.commit()
        return
    if decision.should_attempt_reconnect:
        await _attempt_reconnect(db_session, task=task, redis_client=redis_client)
        return
    if task.llm_account_id is not None:
        await _report_bridge_disconnected(db_session, task=task)
    await _fail_lost_session(db_session, task=task)


async def check_session_bridges(db_session: AsyncSession, *, redis_client: Redis) -> None:
    """
    Раздел 16.2 `check_remote_control_bridges`: проверка каждой задачи с
    сессией. Задача перечитывается перед проверкой: перевод в `failed`
    откатывает транзакцию, и загруженные заранее записи устаревают.
    """
    task_ids = [task.id for task in await find_tasks_requiring_remote_control_check(db_session)]
    for task_id in task_ids:
        task = await db_session.get(Task, task_id, populate_existing=True)
        if task is not None and task.status in SESSION_ACTIVE_STATUSES:
            with bind_task_context(task_id):
                await check_task_bridge(db_session, task=task, redis_client=redis_client)
