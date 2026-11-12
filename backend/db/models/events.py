"""Таблица `events` — лента событий пользователя и администраторов (раздел 18.4 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import EventAudience, EventCategory
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class Event(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """
    Одно событие ленты: у `user` — адресат `user_id`, у `admins` — все
    активные администраторы (`user_id` пуст).
    """

    __tablename__ = "events"
    __table_args__ = (
        sa.Index("ix_events_user_id_created_at", "user_id", sa.text("created_at DESC")),
        sa.Index("ix_events_audience_created_at", "audience", sa.text("created_at DESC")),
        sa.CheckConstraint(
            "(audience = 'user') = (user_id IS NOT NULL)",
            name="ck_events_audience_user_id",
        ),
    )

    audience: Mapped[EventAudience] = mapped_column(pg_enum(EventAudience, name="event_audience"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    category: Mapped[EventCategory] = mapped_column(pg_enum(EventCategory, name="event_category"))
    # Значение `services.notifications.NotificationEvent`.
    event_type: Mapped[str] = mapped_column(sa.String)
    title: Mapped[str] = mapped_column(sa.String)
    body: Mapped[str] = mapped_column(sa.Text)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL"),
    )
