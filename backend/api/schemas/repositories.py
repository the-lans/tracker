"""
Репозитории и шаблоны (раздел 3.1).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class RepositoryCreateRequest(BaseModel):
    name: str
    git_url: str
    default_template_id: uuid.UUID | None = None
    deploy_key: str


class RepositoryUpdateRequest(BaseModel):
    name: str | None = None
    git_url: str | None = None
    default_template_id: uuid.UUID | None = None
    deploy_key: str | None = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_url: str
    default_template_id: uuid.UUID | None


class TemplateCreateRequest(BaseModel):
    name: str
    files: dict[str, Any]
    mcp_server_ids: list[uuid.UUID] = []


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    files: dict[str, Any] | None = None
    mcp_server_ids: list[uuid.UUID] | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    files: dict[str, Any]
    mcp_server_ids: list[uuid.UUID]
    created_by: uuid.UUID
