"""
Пользователи, профиль, Jira, SFTP, допуск email и периодические задачи
(раздел 15.5, 15.6, 19.1, 19.2, 19.6).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from db.models.enums import (
    PeriodicRunStatus,
    PeriodicScheduleType,
    UserRole,
)
from services.sftp_access import SFTP_LOGIN_PATTERN
from services.ssh_keys import MAX_PUBLIC_KEY_LENGTH, fingerprint_of_public_key


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    os_username: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    # Раздел 15.1, 15.5: публичный ключ SFTP-шлюза, его отпечаток и последний
    # вход по нему — и в профиле, и в «Пользователях».
    ssh_public_key: str | None
    ssh_key_last_used_at: datetime | None
    # Раздел 15.6: личный доступ к Jira; токен не отдаётся — только признак.
    jira_email: str | None = None
    jira_token_encrypted: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ssh_key_fingerprint(self) -> str | None:
        if self.ssh_public_key is None:
            return None
        return fingerprint_of_public_key(self.ssh_public_key)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def jira_token_set(self) -> bool:
        return self.jira_token_encrypted is not None


class JiraConnectionUpdateRequest(BaseModel):
    """
    Раздел 15.6: ``jira_token`` — `None` оставить сохранённый, пустая строка — удалить.
    """

    jira_email: str | None = None
    jira_token: str | None = None


class JiraServerResponse(BaseModel):
    """
    Раздел 15.6: адрес Jira, заданный администратором; `None` — импорт недоступен.
    """

    jira_url: str | None


class JiraAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    filename: str
    size: int


class JiraIssueDraftResponse(BaseModel):
    """Раздел 15.6: поля формы новой задачи из задачи Jira."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    description: str
    issue_url: str
    attachments: list[JiraAttachmentResponse]


class JiraAttachmentCopyResponse(BaseModel):
    """Раздел 15.6: вложения Jira ещё копируются в артефакты задачи."""

    pending: bool


class SftpConnectionResponse(BaseModel):
    """Раздел 15.1: данные подключения к SFTP-шлюзу для инструкции в профиле."""

    host: str
    port: int
    username: str | None
    host_key_fingerprint: str | None


class SshKeyUpdateRequest(BaseModel):
    public_key: str = Field(max_length=MAX_PUBLIC_KEY_LENGTH)


class UserUpdateRequest(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    # Раздел 3.1, 15.5: логин SFTP-шлюза назначает администратор.
    os_username: str | None = Field(default=None, pattern=SFTP_LOGIN_PATTERN)


class AllowedEmailCreateRequest(BaseModel):
    email: str


class AllowedEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    added_by: uuid.UUID | None
    created_at: datetime


class PeriodicTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str
    task_path: str
    schedule_type: PeriodicScheduleType
    interval_seconds: int | None
    crontab_expression: str | None
    is_enabled: bool
    last_run_at: datetime | None
    last_run_status: PeriodicRunStatus | None
    next_run_at: datetime | None


class PeriodicTaskUpdateRequest(BaseModel):
    """Раздел 16.1: расписание редактируется без перезапуска процессов —
    ровно одно из двух полей заполнено, в соответствии с `schedule_type`
    текущей записи (менять сам `schedule_type` не поддерживается — это
    сменило бы природу задачи, не просто её расписание)."""

    interval_seconds: int | None = None
    crontab_expression: str | None = None
    is_enabled: bool | None = None
