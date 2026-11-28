"""История исполнения и очистки тестовых окружений."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.mixins import CreatedAtMixin, JsonValue, UUIDPrimaryKeyMixin


class TestRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "test_runs"
    __table_args__ = (
        sa.UniqueConstraint("task_id", "idempotency_key"),
        sa.Index("ix_test_runs_status", "status", "cleanup_status"),
    )
    __test__ = False

    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"), index=True)
    repository_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("repositories.id"))
    idempotency_key: Mapped[uuid.UUID]
    check: Mapped[str] = mapped_column(sa.String)
    source: Mapped[str] = mapped_column(sa.String)
    profile: Mapped[JsonValue] = mapped_column(JSONB)
    repository_name: Mapped[str] = mapped_column(sa.String)
    status: Mapped[str] = mapped_column(sa.String, default="queued")
    cleanup_status: Mapped[str] = mapped_column(sa.String, default="pending")
    cleanup_error: Mapped[str | None] = mapped_column(sa.Text)
    exit_code: Mapped[int | None]
    logs: Mapped[str] = mapped_column(sa.Text, default="")
    error: Mapped[str | None] = mapped_column(sa.Text)
    report_files: Mapped[list[str]] = mapped_column(JSONB, default=list)
    cancel_requested: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
