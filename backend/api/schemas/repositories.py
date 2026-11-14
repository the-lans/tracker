"""
Репозитории и шаблоны (раздел 3.1).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from db.models.repositories import DEFAULT_REPOSITORY_BRANCH


class RepositoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    git_url: str
    default_branch: str = DEFAULT_REPOSITORY_BRANCH
    default_template_id: uuid.UUID | None = None
    git_credential_id: uuid.UUID | None = None


class RepositoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    git_url: str | None = None
    default_branch: str | None = None
    default_template_id: uuid.UUID | None = None
    git_credential_id: uuid.UUID | None = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_url: str
    default_branch: str
    default_template_id: uuid.UUID | None
    git_credential_id: uuid.UUID | None


class RepositoryDefaultBranchRequest(BaseModel):
    """Раздел 3.1: адрес и доступ из формы репозитория — она может быть ещё не сохранена."""

    model_config = ConfigDict(extra="forbid")

    git_url: str
    git_credential_id: uuid.UUID | None = None


class RepositoryDefaultBranchResponse(BaseModel):
    default_branch: str


class TemplateCreateRequest(BaseModel):
    name: str
    files: dict[str, Any]
    # Раздел 15.1: пути из `files`, содержимое которых загружено с диска.
    uploaded_file_paths: list[str] = []
    mcp_server_ids: list[uuid.UUID] = []


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    files: dict[str, Any] | None = None
    uploaded_file_paths: list[str] | None = None
    mcp_server_ids: list[uuid.UUID] | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    files: dict[str, Any]
    uploaded_file_paths: list[str]
    mcp_server_ids: list[uuid.UUID]
    created_by: uuid.UUID
