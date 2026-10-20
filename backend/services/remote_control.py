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

from app_logging.config import get_logger
from db.models.enums import RemoteControlStatus
from services.errors import ConflictError
from services.task_control import request_bridge_reconnect
from services.task_status import SESSION_ACTIVE_STATUSES

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

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
    task.remote_control_status = RemoteControlStatus.RECONNECTING
    await db_session.commit()
    await request_bridge_reconnect(redis_client, task.id)
