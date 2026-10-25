"""
Системные настройки и интеграции (раздел 15.5).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.common import HTTP_URL_PATTERN, MaxRetries, RetryBaseDelaySeconds, TimeoutSeconds


class SystemSettingsBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_timeout_seconds: TimeoutSeconds
    default_max_retries: MaxRetries
    default_retry_base_delay_seconds: RetryBaseDelaySeconds
    default_runner_image_python: str = Field(min_length=1)
    default_runner_image_bash: str = Field(min_length=1)


class IntegrationsResponse(BaseModel):
    """Раздел 15.5: токен GitLab не возвращается — только признак, что он сохранён."""

    gitlab_url: str | None
    gitlab_token_set: bool
    jira_url: str | None


class IntegrationsUpdateRequest(BaseModel):
    gitlab_url: str | None = Field(default=None, pattern=HTTP_URL_PATTERN)
    # `None` — оставить сохранённый токен, пустая строка — удалить.
    gitlab_token: str | None = None
    # Раздел 15.6: сервер Jira, к которому обращается импорт задач.
    jira_url: str | None = Field(default=None, pattern=HTTP_URL_PATTERN)


class LibraryUsageResponse(BaseModel):
    """Раздел 15.5: в скольких задачах используется промт библиотеки."""

    node_id: uuid.UUID
    task_count: int
