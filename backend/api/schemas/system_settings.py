"""
Системные настройки, интеграции и резервное копирование в S3 (разделы 15.5, 20.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.common import HTTP_URL_PATTERN, MaxRetries, RetryBaseDelaySeconds, TimeoutSeconds
from db.models.enums import BackupRunStatus
from db.models.settings import (
    DEFAULT_BACKUP_FOLDER,
    DEFAULT_BACKUP_RETENTION_COUNT,
    MAX_BACKUP_RETENTION_COUNT,
    MIN_BACKUP_RETENTION_COUNT,
)
from db.models.users import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from services.backup.settings import (
    MAX_ACCESS_KEY_LENGTH,
    MAX_FOLDER_LENGTH,
    MAX_PASSPHRASE_LENGTH,
)

_MAX_BACKUP_FIELD_LENGTH = 255


class SystemSettingsBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_timeout_seconds: TimeoutSeconds
    default_max_retries: MaxRetries
    default_retry_base_delay_seconds: RetryBaseDelaySeconds
    # Раздел 14.4: ночное окно по московскому времени.
    night_window_start: time
    night_window_end: time
    # Раздел 17.2: сколько дней хранится журнал `app_logs`; 0 — бессрочно.
    app_logs_retention_days: int = Field(ge=MIN_RETENTION_DAYS, le=MAX_RETENTION_DAYS)
    # Раздел 15.8: начало дня «Дейли» по московскому времени.
    day_start_time: time


class IntegrationsResponse(BaseModel):
    """
    Раздел 15.5: доступ к GitLab API задаётся в учётных данных Git, здесь — только Jira.
    """

    jira_url: str | None


class IntegrationsUpdateRequest(BaseModel):
    # Раздел 15.6: сервер Jira, к которому обращается импорт задач.
    jira_url: str | None = Field(default=None, pattern=HTTP_URL_PATTERN)


class LibraryUsageResponse(BaseModel):
    """Раздел 15.5: в скольких задачах используется промт библиотеки."""

    node_id: uuid.UUID
    task_count: int


class BackupRunResponse(BaseModel):
    """Раздел 20.4: итог последнего бэкапа или проверки восстановления."""

    model_config = ConfigDict(from_attributes=True)

    status: BackupRunStatus
    started_at: datetime
    finished_at: datetime | None
    object_key: str | None
    size_bytes: int | None
    skipped_files: list[dict[str, str]]
    error_message: str | None


class BackupSettingsResponse(BaseModel):
    """Раздел 15.5: настройки бэкапа в S3; секреты — только признак «задан»."""

    enabled: bool
    endpoint: str | None
    region: str | None
    bucket: str | None
    access_key: str | None
    secret_key_set: bool
    folder: str
    retention_count: int
    passphrase_set: bool
    last_backup: BackupRunResponse | None
    last_verify: BackupRunResponse | None


class BackupSettingsUpdateRequest(BaseModel):
    """Пустой секрет или пароль — оставить сохранённый."""

    enabled: bool
    endpoint: str | None = Field(default=None, max_length=_MAX_BACKUP_FIELD_LENGTH)
    region: str | None = Field(default=None, max_length=_MAX_BACKUP_FIELD_LENGTH)
    bucket: str | None = Field(default=None, max_length=_MAX_BACKUP_FIELD_LENGTH)
    access_key: str | None = Field(default=None, max_length=MAX_ACCESS_KEY_LENGTH)
    secret_key: str | None = Field(default=None, max_length=MAX_ACCESS_KEY_LENGTH)
    folder: str = Field(default=DEFAULT_BACKUP_FOLDER, max_length=MAX_FOLDER_LENGTH)
    retention_count: int = Field(
        default=DEFAULT_BACKUP_RETENTION_COUNT,
        ge=MIN_BACKUP_RETENTION_COUNT,
        le=MAX_BACKUP_RETENTION_COUNT,
    )
    passphrase: str | None = Field(default=None, max_length=MAX_PASSPHRASE_LENGTH)


class BackupConnectionCheckResponse(BaseModel):
    ok: bool
    message: str
