"""
Запись критичных событий в `app_logs` вне транзакции вызывающего кода (раздел 17.2 ТЗ).

Нужна там, где своей сессии БД нет или ей нельзя доверять — например, в
обработчике необработанного исключения API: сессия запроса к этому моменту
могла остаться в незавершённой транзакции. Сбой самой записи не должен
подменять исходную ошибку и задерживать ответ: запись ограничена по времени,
любая её ошибка (включая недоступную БД) только логируется в stdout.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app_logging.config import get_logger
from db.models.enums import AppLogLevel
from db.models.logs import AppLog
from db.session import async_session_factory

logger = get_logger("app_logs")

# Запись не должна заметно задерживать ответ, даже если БД не отвечает.
WRITE_TIMEOUT_SECONDS = 2.0


async def _insert(app_log: AppLog) -> None:
    async with async_session_factory() as session:
        session.add(app_log)
        await session.commit()


async def write_app_log(
    *,
    level: AppLogLevel,
    source: str,
    message: str,
    context: dict[str, Any],
    task_id: uuid.UUID | None = None,
) -> None:
    app_log = AppLog(level=level, source=source, message=message, context=context, task_id=task_id)
    try:
        await asyncio.wait_for(_insert(app_log), timeout=WRITE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — сбой записи (БД недоступна, таймаут) не роняет вызывающий код
        logger.error("app_log_write_failed", source=source, error=repr(exc))
