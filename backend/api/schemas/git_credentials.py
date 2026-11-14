"""
Схемы раздела «Учётные данные Git» (разделы 3.1, 15.5).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.common import HTTP_URL_PATTERN

MAX_NAME_LENGTH = 200
MAX_HOST_LENGTH = 253
MAX_SECRET_LENGTH = 65536
MAX_GIT_URL_LENGTH = 2048
DEFAULT_HTTPS_USERNAME = "oauth2"


class CredentialInput(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    kind: Literal["https_token", "ssh_key"]
    host: str = Field(min_length=1, max_length=MAX_HOST_LENGTH)
    username: str = Field(default=DEFAULT_HTTPS_USERNAME, min_length=1, max_length=MAX_NAME_LENGTH)
    secret: str | None = Field(default=None, max_length=MAX_SECRET_LENGTH)
    # Раздел 16.2: статус MR репозиториев с этими учётными данными.
    gitlab_api_enabled: bool = False
    # `None` — оставить сохранённый токен API, пустая строка — удалить.
    gitlab_api_token: str | None = Field(default=None, max_length=MAX_SECRET_LENGTH)
    gitlab_api_url: str | None = Field(default=None, pattern=HTTP_URL_PATTERN)
    # Раздел 19.3: ключи Git-сервера для SSH. `None` — оставить сохранённые,
    # пустая строка — сбросить (запомнятся при следующем подключении).
    ssh_known_hosts: str | None = Field(default=None, max_length=MAX_SECRET_LENGTH)


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    kind: str
    host: str
    username: str
    gitlab_api_enabled: bool
    gitlab_api_url: str | None
    gitlab_api_token_set: bool
    # Пусто — ключ хоста ещё не получен.
    ssh_host_key_fingerprints: list[str]


class CredentialCheckRequest(BaseModel):
    git_url: str = Field(min_length=1, max_length=MAX_GIT_URL_LENGTH)


class CredentialCheckResponse(BaseModel):
    read_access: bool
    gitlab_api: str
    # Раздел 19.3: ключ, запомненный при этой проверке, — для сверки администратором.
    ssh_host_key_fingerprints: list[str]
