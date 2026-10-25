"""
Общие ограничения полей схем API.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

HTTP_URL_PATTERN = r"^https?://\S+$"

# Границы значений выполнения ноды — те же, что у «Системных настроек» (раздел 15.5).
_MAX_TIMEOUT_SECONDS = 24 * 60 * 60
_MAX_RETRIES = 10
_MAX_RETRY_DELAY_SECONDS = 60 * 60
TimeoutSeconds = Annotated[int, Field(ge=1, le=_MAX_TIMEOUT_SECONDS)]
MaxRetries = Annotated[int, Field(ge=1, le=_MAX_RETRIES)]
RetryBaseDelaySeconds = Annotated[int, Field(ge=0, le=_MAX_RETRY_DELAY_SECONDS)]
