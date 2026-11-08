"""Таблица `system_settings` — «Системные настройки» админки (раздел 15.5 ТЗ)."""

from __future__ import annotations

from datetime import time

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base

# Единственная строка настроек инстанса.
SYSTEM_SETTINGS_ROW_ID = 1
# Раздел 14.4: ночное окно по московскому времени.
DEFAULT_NIGHT_WINDOW_START = time(3, 15)
DEFAULT_NIGHT_WINDOW_END = time(7, 0)


class SystemSettings(Base):
    """
    Значения по умолчанию для новых нод и раннеров script-нод, интеграции:
    GitLab (адрес и токен API — настройки системы, а не переменные окружения
    задач: в промты и скрипты они не попадают, раздел 15.5, 19.4) и адрес
    Jira (раздел 15.6: сервер, к которому обращается импорт задач, выбирает
    администратор, личный токен — в профиле пользователя).

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
    # Не используются: образ script-ноды без `docker_image` — стандартный
    # (`services/nodes/script.py::DEFAULT_RUNNER_IMAGES`). Столбцы остаются в
    # БД до следующего релиза (ТЗ 20.6): ими пользуется предыдущая версия.
    default_runner_image_python: Mapped[str] = mapped_column(sa.String)
    default_runner_image_bash: Mapped[str] = mapped_column(sa.String)
    # `gitlab_url`, `gitlab_token_encrypted` остаются в БД до следующего релиза
    # (ТЗ 20.6), но не используются: доступ к GitLab API — в `git_credentials`.
    jira_url: Mapped[str | None] = mapped_column(sa.String)
    night_window_start: Mapped[time] = mapped_column(
        sa.Time,
        default=DEFAULT_NIGHT_WINDOW_START,
        server_default=DEFAULT_NIGHT_WINDOW_START.isoformat(timespec="minutes"),
    )
    night_window_end: Mapped[time] = mapped_column(
        sa.Time,
        default=DEFAULT_NIGHT_WINDOW_END,
        server_default=DEFAULT_NIGHT_WINDOW_END.isoformat(timespec="minutes"),
    )
