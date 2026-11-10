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
from services.llm_account_choice import LimitState

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


class LlmAccountFields(BaseModel):
    """Поля записи `llm_accounts`, которые видит пользователь."""

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


class LlmAccountResponse(LlmAccountFields):
    """Раздел 15.1: аккаунт и его состояние лимита для бейджа."""

    limit_state: LimitState
    # Когда состояние кончится: сброс окна или недели; None — не ограничено.
    limit_state_until: datetime | None
    # Задачи в работе, которые сейчас идут на этом аккаунте.
    active_tasks: int


class LlmLoginStartResponse(BaseModel):
    url: str
    state: str
    expires_at: datetime


class LlmLoginCallbackRequest(BaseModel):
    redirect_url: str = Field(min_length=1, max_length=_REDIRECT_URL_MAX_LENGTH)


class LlmLoginStatusResponse(BaseModel):
    state: OAuthState
    error: str | None


class LlmThresholdsUpdateRequest(BaseModel):
    """Раздел 19.7: порог 5-часового окна лимита, в процентах; недельного порога нет."""

    five_hour_pct: int = Field(ge=MIN_LLM_SWITCH_THRESHOLD_PCT, le=MAX_LLM_SWITCH_THRESHOLD_PCT)


class LlmCompactUpdateRequest(BaseModel):
    """Раздел 19.7: «Сжимать контекст при смене LLM-аккаунта»."""

    enabled: bool
