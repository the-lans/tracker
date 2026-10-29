"""
Запись выполнения в `node_logs` (раздел 3.1, 13.4 ТЗ) — одинаковая у нод
пайплайна, ручных запросов, пересказа родителя и разбора конфликта ребейза:
запись `running` фиксируется до хода агента, затем — итог или остановка.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from db.models.enums import NodeLogStatus, NodeType

# Причина в ленте (раздел 15.2); подробности сбоя — в `app_logs`, не пользователю.
SESSION_ERROR_MESSAGE = "Сбой сессии Claude Code — подробности в журнале ошибок у администратора"

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.claude_agent import ClaudeCodeSession
    from db.models.logs import NodeLog
    from services.nodes.dispatch import NodeExecutionOutcome


async def start_node_log(db_session: AsyncSession, node_log: NodeLog) -> NodeLog:
    """
    Запись `running` видна ленте и callback разрешений (его сессии БД) до
    начала выполнения — поэтому сразу коммитится.
    """
    node_log.status = NodeLogStatus.RUNNING
    node_log.started_at = datetime.now(UTC)
    db_session.add(node_log)
    await db_session.commit()
    return node_log


def mark_node_log_stopped(
    node_log: NodeLog,
    *,
    node_type: NodeType | None,
    claude_session: ClaudeCodeSession,
) -> None:
    """
    Остановка пользователем. Раздел 6.4: полученная до остановки часть
    ответа агента не теряется; у скрипта ответа агента нет.
    """
    node_log.finished_at = datetime.now(UTC)
    node_log.status = NodeLogStatus.STOPPED
    if node_type is not NodeType.SCRIPT:
        node_log.llm_output_text = claude_session.take_partial_turn_text()


def apply_node_outcome(
    node_log: NodeLog,
    outcome: NodeExecutionOutcome,
    *,
    success: bool | None = None,
) -> None:
    """
    Итог выполнения; ``success`` — когда успех определяется не только ходом
    агента (например, конфликт ребейза должен быть ещё и разобран).
    """
    succeeded = outcome.success if success is None else success
    node_log.finished_at = datetime.now(UTC)
    node_log.llm_output_text = outcome.llm_output_text
    node_log.script_stdout = outcome.script_stdout
    node_log.script_exit_code = outcome.script_exit_code
    node_log.error_message = None if succeeded else outcome.error_message
    node_log.status = NodeLogStatus.SUCCESS if succeeded else NodeLogStatus.FAILED
