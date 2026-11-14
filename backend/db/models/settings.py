"""Таблица `system_settings` — «Системные настройки» админки (раздел 15.5 ТЗ)."""

from __future__ import annotations

from datetime import time

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.users import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS

# Единственная строка настроек инстанса.
SYSTEM_SETTINGS_ROW_ID = 1
# Раздел 14.4: ночное окно по московскому времени.
DEFAULT_NIGHT_WINDOW_START = time(3, 15)
DEFAULT_NIGHT_WINDOW_END = time(7, 0)
# Раздел 20.4: папка в бакете и число хранимых копий по умолчанию.
DEFAULT_BACKUP_FOLDER = "Tracker"
DEFAULT_BACKUP_RETENTION_COUNT = 7
MIN_BACKUP_RETENTION_COUNT = 1
MAX_BACKUP_RETENTION_COUNT = 365
# Раздел 17.2: сколько дней хранится журнал `app_logs`; 0 — бессрочно.
DEFAULT_APP_LOGS_RETENTION_DAYS = 30


class SystemSettings(Base):
    """
    Значения по умолчанию для новых нод и раннеров script-нод, интеграции:
    GitLab (адрес и токен API — настройки системы, а не переменные окружения
    задач: в промты и скрипты они не попадают, раздел 15.5, 19.4) и адрес
    Jira (раздел 15.6: сервер, к которому обращается импорт задач, выбирает
    администратор, личный токен — в профиле пользователя).
    Резервное копирование в S3 (раздел 20.4): хранилище, папка, число копий
    и пароль шифрования. Срок хранения журнала `app_logs` (раздел 17.2).

    Одна строка на инстанс: `id` всегда равен `SYSTEM_SETTINGS_ROW_ID`.
    """

    __tablename__ = "system_settings"
    __table_args__ = (
        sa.CheckConstraint(f"id = {SYSTEM_SETTINGS_ROW_ID}", name="ck_system_settings_single_row"),
        sa.CheckConstraint(
            "backup_retention_count BETWEEN "
            f"{MIN_BACKUP_RETENTION_COUNT} AND {MAX_BACKUP_RETENTION_COUNT}",
            name="ck_system_settings_backup_retention_count",
        ),
        sa.CheckConstraint(
            f"app_logs_retention_days BETWEEN {MIN_RETENTION_DAYS} AND {MAX_RETENTION_DAYS}",
            name="ck_system_settings_app_logs_retention_days",
        ),
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
    # Раздел 20.4: резервное копирование в S3. Секреты — зашифрованы
    # (services/crypto.py), API их не возвращает.
    backup_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    backup_s3_endpoint: Mapped[str | None] = mapped_column(sa.String)
    backup_s3_region: Mapped[str | None] = mapped_column(sa.String)
    backup_s3_bucket: Mapped[str | None] = mapped_column(sa.String)
    backup_s3_access_key: Mapped[str | None] = mapped_column(sa.String)
    backup_s3_secret_key_encrypted: Mapped[str | None] = mapped_column(sa.Text)
    backup_s3_folder: Mapped[str] = mapped_column(
        sa.String,
        default=DEFAULT_BACKUP_FOLDER,
        server_default=DEFAULT_BACKUP_FOLDER,
    )
    backup_retention_count: Mapped[int] = mapped_column(
        sa.Integer,
        default=DEFAULT_BACKUP_RETENTION_COUNT,
        server_default=str(DEFAULT_BACKUP_RETENTION_COUNT),
    )
    backup_passphrase_encrypted: Mapped[str | None] = mapped_column(sa.Text)
    app_logs_retention_days: Mapped[int] = mapped_column(
        sa.Integer,
        default=DEFAULT_APP_LOGS_RETENTION_DAYS,
        server_default=str(DEFAULT_APP_LOGS_RETENTION_DAYS),
    )
