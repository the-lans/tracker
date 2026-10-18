"""Таблица `llm_accounts` (раздел 3.1 ТЗ)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import LlmAccountStatus
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class LlmAccount(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "llm_accounts"

    label: Mapped[str] = mapped_column(sa.String)
    # Путь к уже вручную настроенной (`claude auth login`) конфигурационной
    # директории аккаунта — провижининг вне периметра проекта.
    claude_config_dir: Mapped[str] = mapped_column(sa.String)
    status: Mapped[LlmAccountStatus] = mapped_column(
        pg_enum(LlmAccountStatus, name="llm_account_status"),
        default=LlmAccountStatus.ACTIVE,
    )
