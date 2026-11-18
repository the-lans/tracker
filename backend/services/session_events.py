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
    """Воркер открывает сессию задачи с чистого листа — до первого хода."""
    add_session_event(db_session, task_id=task_id, kind=TaskSessionEventKind.SESSION_STARTED)
    await db_session.commit()
