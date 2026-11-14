"""
«Дейли» (разделы 3.1, 15.8, 19.8 ТЗ): отметки задач по дням, события дня,
планы на день, шаблон плана и подключение к Google Calendar. Все записи
личные — их видит и меняет только владелец (`user_id`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import DailyEventSource, GoogleCalendarStatus
from db.models.mixins import CreatedAtMixin, CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin, pg_enum

# Раздел 19.8: без выбора пользователя синхронизируется основной календарь.
PRIMARY_CALENDAR_ID = "primary"


class TaskDayMark(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """
    Отметка «задача на этот день» — только намерение пользователя: задачу она
    не запускает и на следующий день не переносится.
    """

    __tablename__ = "task_day_marks"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "task_id", "day", name="uq_task_day_marks_user_task_day"),
        sa.Index("ix_task_day_marks_user_day", "user_id", "day"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(sa.Date)


class DailyEvent(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    """
    Событие дня: ручное или из Google Calendar (`calendar_id` + `external_id`).
    Событие без времени (`starts_at IS NULL`) — на весь день; многодневное
    занимает дни с `day` по `end_day` включительно.
    """

    __tablename__ = "daily_events"
    __table_args__ = (
        sa.CheckConstraint("end_day >= day", name="ck_daily_events_end_day"),
        sa.Index("ix_daily_events_user_day", "user_id", "day"),
        sa.Index(
            "uq_daily_events_google_event",
            "user_id",
            "calendar_id",
            "external_id",
            unique=True,
            postgresql_where=sa.text("source = 'google'"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    source: Mapped[DailyEventSource] = mapped_column(
        pg_enum(DailyEventSource, name="daily_event_source"),
    )
    day: Mapped[date] = mapped_column(sa.Date)
    end_day: Mapped[date] = mapped_column(sa.Date)
    starts_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    title: Mapped[str] = mapped_column(sa.String)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    hidden: Mapped[bool] = mapped_column(sa.Boolean, default=False, server_default=sa.false())
    calendar_id: Mapped[str | None] = mapped_column(sa.String)
    external_id: Mapped[str | None] = mapped_column(sa.String)


class DailyPlan(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    """
    План на день: текст собран по шаблону пользователя и дальше правится
    вручную — один план на пользователя в день.
    """

    __tablename__ = "daily_plans"
    __table_args__ = (sa.UniqueConstraint("user_id", "day", name="uq_daily_plans_user_day"),)

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    day: Mapped[date] = mapped_column(sa.Date)
    content: Mapped[str] = mapped_column(sa.Text)


class DailyPlanTemplate(Base):
    """Шаблон плана на день; без записи действует шаблон по умолчанию."""

    __tablename__ = "daily_plan_templates"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), primary_key=True)
    content: Mapped[str] = mapped_column(sa.Text)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class GoogleCalendarConnection(CreatedUpdatedAtMixin, Base):
    """
    Доступ к календарю указанного Google-аккаунта только на чтение (раздел
    19.8). Refresh-токен зашифрован (раздел 19.4), API его не возвращает.
    """

    __tablename__ = "google_calendar_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), primary_key=True)
    google_email: Mapped[str] = mapped_column(sa.String)
    refresh_token_encrypted: Mapped[str] = mapped_column(sa.Text)
    calendar_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        default=lambda: [PRIMARY_CALENDAR_ID],
        server_default=sa.text(f"'[\"{PRIMARY_CALENDAR_ID}\"]'::jsonb"),
    )
    status: Mapped[GoogleCalendarStatus] = mapped_column(
        pg_enum(GoogleCalendarStatus, name="google_calendar_status"),
        default=GoogleCalendarStatus.CONNECTED,
        server_default=GoogleCalendarStatus.CONNECTED.value,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(sa.Text)
