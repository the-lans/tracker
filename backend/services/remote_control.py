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

from db.models.enums import RemoteControlStatus

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
