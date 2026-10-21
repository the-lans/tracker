"""Таблица `periodic_tasks` (раздел 3.1, 16 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import PeriodicRunStatus, PeriodicScheduleType
from db.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class PeriodicTask(UUIDPrimaryKeyMixin, Base):
    """Расписание периодической задачи (раздел 16.1 ТЗ).

    Ровно одно из ``interval_seconds``/``crontab_expression`` заполнено —
    прямое следствие ``schedule_type`` (интервал либо crontab-выражение, не
    оба сразу).
    """

    __tablename__ = "periodic_tasks"
    __table_args__ = (
        sa.CheckConstraint(
            "(schedule_type = 'interval' AND interval_seconds IS NOT NULL) "
            "OR (schedule_type = 'crontab' AND crontab_expression IS NOT NULL)",
            name="ck_periodic_tasks_schedule_type_matches_payload",
        ),
    )

    name: Mapped[str] = mapped_column(sa.String, unique=True)
    display_name: Mapped[str] = mapped_column(sa.String)
    description: Mapped[str] = mapped_column(sa.Text)
    task_path: Mapped[str] = mapped_column(sa.String)
    schedule_type: Mapped[PeriodicScheduleType] = mapped_column(
        pg_enum(PeriodicScheduleType, name="periodic_schedule_type"),
    )
    interval_seconds: Mapped[int | None] = mapped_column(sa.Integer)
    crontab_expression: Mapped[str | None] = mapped_column(sa.String)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_run_status: Mapped[PeriodicRunStatus | None] = mapped_column(
        pg_enum(PeriodicRunStatus, name="periodic_run_status"),
    )
    next_run_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # NULL — запись создана системой при установке (раздел 3.1, 20.2 п. 8).
    updated_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
