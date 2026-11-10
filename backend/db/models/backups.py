"""Таблица `backup_runs` — запуски бэкапа в S3 и проверки восстановления (раздел 20.4 ТЗ)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import BackupRunKind, BackupRunStatus
from db.models.mixins import JsonValue, UUIDPrimaryKeyMixin, pg_enum


class BackupRun(UUIDPrimaryKeyMixin, Base):
    """Один запуск `backup_to_s3` или `verify_s3_backup`; хранятся последние по каждому виду."""

    __tablename__ = "backup_runs"
    __table_args__ = (
        sa.Index("ix_backup_runs_kind_started_at", "kind", sa.text("started_at DESC")),
    )

    kind: Mapped[BackupRunKind] = mapped_column(pg_enum(BackupRunKind, name="backup_run_kind"))
    status: Mapped[BackupRunStatus] = mapped_column(
        pg_enum(BackupRunStatus, name="backup_run_status"),
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    object_key: Mapped[str | None] = mapped_column(sa.String)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger)
    sha256: Mapped[str | None] = mapped_column(sa.String)
    # Пропущенные файлы: {"component", "path", "reason"}.
    skipped_files: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    details: Mapped[JsonValue] = mapped_column(
        JSONB,
        default=dict,
        server_default=sa.text("'{}'::jsonb"),
    )
    error_message: Mapped[str | None] = mapped_column(sa.Text)
