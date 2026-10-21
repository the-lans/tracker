"""Таблица `llm_accounts` (раздел 3.1 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import LlmAccountStatus
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class LlmAccount(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "llm_accounts"

    label: Mapped[str] = mapped_column(sa.String)
    # Путь к уже вручную настроенной (`claude auth login`) конфигурационной
    # директории аккаунта — её настраивает администратор (раздел 19.5).
    # Уникален: директории аккаунтов не пересекаются.
    claude_config_dir: Mapped[str] = mapped_column(sa.String, unique=True)
    status: Mapped[LlmAccountStatus] = mapped_column(
        pg_enum(LlmAccountStatus, name="llm_account_status"),
        default=LlmAccountStatus.ACTIVE,
    )
    # Время сброса окна лимита из последнего `RateLimitEvent` со статусом
    # `rejected` (раздел 16.2, `check_llm_account_limits`).
    rate_limit_resets_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Раздел 19.2: аккаунт личный — владелец тот, кто его завёл.
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)
