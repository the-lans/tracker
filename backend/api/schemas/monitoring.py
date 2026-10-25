"""
Web Push и мониторинг (раздел 15.5, 18.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from db.models.enums import (
    AppLogLevel,
    NodeLogStatus,
    NodeLogTriggerType,
)


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    """Форма `PushSubscriptionJSON` стандарта Push API — то, что отдаёт
    `PushSubscription.toJSON()` в браузере."""

    endpoint: str
    keys: PushSubscriptionKeys


class VapidPublicKeyResponse(BaseModel):
    public_key: str


class NodeRunResponse(BaseModel):
    """Раздел 13.4: строка сводки выполнения нод по всем задачам."""

    model_config = ConfigDict(from_attributes=True)

    node_log_id: uuid.UUID
    task_id: uuid.UUID
    task_code: str
    node_id: uuid.UUID | None
    node_name: str | None
    trigger_type: NodeLogTriggerType
    attempt_number: int
    status: NodeLogStatus
    started_at: datetime | None
    finished_at: datetime | None


class ActiveCeleryTaskResponse(BaseModel):
    """Раздел 15.5: активная Celery-задача на одном из воркеров."""

    model_config = ConfigDict(from_attributes=True)

    worker: str
    celery_task_id: str
    name: str
    started_at: datetime | None
    task_id: uuid.UUID | None
    task_code: str | None


class AppLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    level: AppLogLevel
    source: str
    message: str
    context: dict[str, Any]
    task_id: uuid.UUID | None
    created_at: datetime
