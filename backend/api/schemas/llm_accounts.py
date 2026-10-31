"""
LLM-аккаунты (разделы 3.1, 15.1, 19.5, 19.7).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from clients.cliproxy import OAuthState
from db.models.enums import LlmAccountStatus, ReasoningEffort
from db.models.users import MAX_LLM_SWITCH_THRESHOLD_PCT, MIN_LLM_SWITCH_THRESHOLD_PCT

_LABEL_MAX_LENGTH = 200
_REDIRECT_URL_MAX_LENGTH = 4096


class LlmProviderResponse(BaseModel):
    id: str
    label: str
    # Опрашивается ли расход окон: без него аккаунт переключается только по лимиту.
    reports_usage: bool
    plan_prompt_allowed: bool


class LlmAccountCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=_LABEL_MAX_LENGTH)
    provider: str


class LlmAccountUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=_LABEL_MAX_LENGTH)
    default_model: str | None = Field(default=None, min_length=1)
    default_effort: ReasoningEffort | None = None
    enabled: bool | None = None


class LlmAccountOrderRequest(BaseModel):
    account_ids: list[uuid.UUID]


class LlmAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    provider: str
    signed_in: bool
    default_model: str | None
    default_effort: ReasoningEffort
    switch_order: int
    status: LlmAccountStatus
    rate_limit_resets_at: datetime | None
    usage_5h_pct: Decimal | None
    usage_week_pct: Decimal | None
    usage_5h_resets_at: datetime | None
    usage_week_resets_at: datetime | None
    usage_checked_at: datetime | None
    created_by: uuid.UUID


class LlmLoginStartResponse(BaseModel):
    url: str
    state: str


class LlmLoginCallbackRequest(BaseModel):
    redirect_url: str = Field(min_length=1, max_length=_REDIRECT_URL_MAX_LENGTH)


class LlmLoginStatusResponse(BaseModel):
    state: OAuthState
    error: str | None


class LlmThresholdsUpdateRequest(BaseModel):
    """Раздел 19.7: пороги переключения аккаунта по окнам лимита, в процентах."""

    five_hour_pct: int = Field(ge=MIN_LLM_SWITCH_THRESHOLD_PCT, le=MAX_LLM_SWITCH_THRESHOLD_PCT)
    week_pct: int = Field(ge=MIN_LLM_SWITCH_THRESHOLD_PCT, le=MAX_LLM_SWITCH_THRESHOLD_PCT)
