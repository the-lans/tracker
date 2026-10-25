"""
MCP-серверы (раздел 3.1, 10.2).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from db.models.enums import (
    McpAuthType,
    McpIsolationMode,
)


class McpServerCreateRequest(BaseModel):
    name: str
    url: str
    auth_type: McpAuthType
    auth_config: str
    has_stateful_resource: bool = False
    isolation_mode: McpIsolationMode | None = None
    isolation_path_template: str | None = None


class McpServerUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    auth_type: McpAuthType | None = None
    auth_config: str | None = None
    has_stateful_resource: bool | None = None
    isolation_mode: McpIsolationMode | None = None
    isolation_path_template: str | None = None


class McpServerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    auth_type: McpAuthType
    is_healthy: bool
    has_stateful_resource: bool
    isolation_mode: McpIsolationMode | None
    isolation_path_template: str | None
