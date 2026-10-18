"""Таблицы `task_library_prompts`, `task_manual_request_queue` (раздел 3.1, 7, 8 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import LibraryPromptRunStatus, ManualRequestStatus, ManualRequestType
from db.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class TaskLibraryPrompt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_library_prompts"

    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"))
    node_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("nodes.id"))
    added_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    last_run_status: Mapped[LibraryPromptRunStatus] = mapped_column(
        pg_enum(LibraryPromptRunStatus, name="library_prompt_run_status"),
        default=LibraryPromptRunStatus.NEVER_RUN,
    )
    last_run_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TaskManualRequestQueue(UUIDPrimaryKeyMixin, Base):
    """Очередь ручных запросов при занятой сессии (раздел 7.3, 8.2 ТЗ).

    ``request_type`` определяет, какое из двух взаимоисключающих полей
    заполнено — ``node_id`` для ``library_prompt``, ``raw_prompt_text`` для
    ``freeform_prompt`` (ТЗ прямо привязывает поле к типу через "Для ...").
    """

    __tablename__ = "task_manual_request_queue"
    __table_args__ = (
        sa.CheckConstraint(
            "(request_type = 'library_prompt' "
            "AND node_id IS NOT NULL AND raw_prompt_text IS NULL) "
            "OR (request_type = 'freeform_prompt' "
            "AND raw_prompt_text IS NOT NULL AND node_id IS NULL)",
            name="ck_task_manual_request_queue_type_matches_payload",
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"))
    request_type: Mapped[ManualRequestType] = mapped_column(
        pg_enum(ManualRequestType, name="manual_request_type"),
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("nodes.id"))
    raw_prompt_text: Mapped[str | None] = mapped_column(sa.Text)
    requested_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    status: Mapped[ManualRequestStatus] = mapped_column(
        pg_enum(ManualRequestStatus, name="manual_request_status"),
        default=ManualRequestStatus.QUEUED,
    )
    processed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
