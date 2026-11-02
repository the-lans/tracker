"""
LLM-прокси в администрировании (раздел 15.5).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from db.models.enums import LlmAccountStatus


class ProxyCredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    provider: str
    disabled: bool
    requires_sign_in: bool
    quota_blocked: bool
    status: str | None
    account_id: uuid.UUID | None
    account_label: str | None
    account_status: LlmAccountStatus | None
    owner_email: str | None
    usage_5h_pct: Decimal | None
    usage_week_pct: Decimal | None


class ProxyStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    available: bool
    error: str | None
    version: str
    latest_version: str | None
    credentials: list[ProxyCredentialResponse]


class ProxyCredentialRequest(BaseModel):
    name: str = Field(min_length=1)
