"""
LLM-аккаунты (раздел 3.1, 19.5).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from db.models.enums import (
    LlmAccountStatus,
)


class LlmAccountCreateRequest(BaseModel):
    label: str
    claude_config_dir: str
    status: LlmAccountStatus = LlmAccountStatus.ACTIVE


class LlmAccountUpdateRequest(BaseModel):
    label: str | None = None
    claude_config_dir: str | None = None
    status: LlmAccountStatus | None = None


class LlmAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    claude_config_dir: str
    status: LlmAccountStatus
    created_by: uuid.UUID
