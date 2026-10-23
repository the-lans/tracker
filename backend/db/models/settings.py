"""Таблица `system_settings` — «Системные настройки» админки (раздел 15.5 ТЗ)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Единственная строка настроек инстанса.
SYSTEM_SETTINGS_ROW_ID = 1


class SystemSettings(Base):
    """
    Значения по умолчанию для новых нод и раннеров script-нод, интеграция с
    GitLab (адрес и токен API — настройки системы, а не переменные окружения
    задач: в промты и скрипты они не попадают, раздел 15.5, 19.4).

    Одна строка на инстанс: `id` всегда равен `SYSTEM_SETTINGS_ROW_ID`.
    """

    __tablename__ = "system_settings"
    __table_args__ = (
        sa.CheckConstraint(f"id = {SYSTEM_SETTINGS_ROW_ID}", name="ck_system_settings_single_row"),
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, default=SYSTEM_SETTINGS_ROW_ID)
    default_timeout_seconds: Mapped[int] = mapped_column(sa.Integer)
    default_max_retries: Mapped[int] = mapped_column(sa.Integer)
    default_retry_base_delay_seconds: Mapped[int] = mapped_column(sa.Integer)
    default_runner_image_python: Mapped[str] = mapped_column(sa.String)
    default_runner_image_bash: Mapped[str] = mapped_column(sa.String)
    gitlab_url: Mapped[str | None] = mapped_column(sa.String)
    gitlab_token_encrypted: Mapped[str | None] = mapped_column(sa.Text)
