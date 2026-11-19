"""
События сессии задачи для ленты чата (раздел 15.2 ТЗ): сброс контекста и
начало новой сессии. Запись идёт в транзакции вызывающего кода, а если
вызывающий код её не коммитит (воркер), — отдельным коммитом.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from db.models.enums import TaskSessionEventKind
from db.models.session_events import TaskSessionEvent
from db.queries.session_events import get_last_session_event, has_node_log_since

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def add_session_event(
    db_session: AsyncSession,
    *,
    task_id: uuid.UUID,
    kind: TaskSessionEventKind,
    at: datetime | None = None,
) -> None:
    """
    Добавляет событие в сессию БД без коммита; ``at`` — момент события в ленте
    (по умолчанию «сейчас»).
    """
    # Время Python, как у `node_logs.started_at`: серверное `now()` — начало
    # транзакции, и порядок событий в ленте мог бы разойтись с записями нод.
    db_session.add(TaskSessionEvent(task_id=task_id, kind=kind, created_at=at or datetime.now(UTC)))


async def record_new_session(db_session: AsyncSession, *, task_id: uuid.UUID) -> None:
    """
    Воркер открывает сессию задачи с чистого листа — до первого хода. Повторный
    старт воркера (сбой или повторная доставка до записи `session_id`) нового
    события не добавляет: с прошлого такого события в задаче не было ни одного хода.
    """
    last = await get_last_session_event(db_session, task_id)
    if (
        last is not None
        and last.kind is TaskSessionEventKind.SESSION_STARTED
        and not await has_node_log_since(db_session, task_id, last.created_at)
    ):
        return
    add_session_event(db_session, task_id=task_id, kind=TaskSessionEventKind.SESSION_STARTED)
    await db_session.commit()
