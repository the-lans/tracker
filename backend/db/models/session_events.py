"""
Таблица `task_session_events` — события сессии задачи для ленты чата (раздел 15.2 ТЗ).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import TaskSessionEventKind
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class TaskSessionEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """
    Сброс контекста или начало новой сессии. Время `created_at` — момент, в
    который событие произошло в ленте: ленту собирают по нему вместе с записями
    `node_logs`.
    """

    __tablename__ = "task_session_events"
    __table_args__ = (
        sa.Index("ix_task_session_events_task_id_created_at", "task_id", "created_at"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id", ondelete="CASCADE"))
    kind: Mapped[TaskSessionEventKind] = mapped_column(
        pg_enum(TaskSessionEventKind, name="task_session_event_kind"),
    )
