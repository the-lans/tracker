"""
Web Push и мониторинг (раздел 15.5, 18.1).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.schemas.system_settings import BackupRunResponse
from db.models.enums import (
    AppLogLevel,
    LlmAccountStatus,
    NodeLogStatus,
    NodeLogTriggerType,
)
from services.container_monitor import ContainerKind
from services.node_stats import StatsPeriod
from services.server_status import Dependency
from services.volume_usage import Volume


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


class DependencyStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Dependency
    ok: bool
    error: str | None


class QueueStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    workers: int
    pending: int | None


class ServerOverviewResponse(BaseModel):
    """Раздел 15.5: сводка состояния сервера на странице «Мониторинг»."""

    model_config = ConfigDict(from_attributes=True)

    dependencies: list[DependencyStatusResponse]
    queues: list[QueueStatusResponse]
    manual_requests_queued: int
    manual_requests_processing: int
    version: str
    deployed_at: datetime | None
    maintenance: bool | None
    last_backup: BackupRunResponse | None
    last_verify: BackupRunResponse | None


class FailingNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: uuid.UUID
    node_name: str
    failed: int


class NodeStatsResponse(BaseModel):
    """Раздел 15.5: итоги запусков нод за сутки или неделю."""

    model_config = ConfigDict(from_attributes=True)

    period: StatsPeriod
    since: datetime
    total: int
    success: int
    failed: int
    stopped: int
    retries: int
    avg_duration_seconds: float | None
    max_duration_seconds: float | None
    top_failing: list[FailingNodeResponse]


class AccountUsageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    provider: str
    owner_email: str
    status: LlmAccountStatus
    usage_5h_pct: Decimal | None
    usage_week_pct: Decimal | None
    usage_5h_resets_at: datetime | None
    usage_week_resets_at: datetime | None
    usage_checked_at: datetime | None
    switches_to_24h: int


class LlmUsageResponse(BaseModel):
    """Раздел 15.5, 19.7: расход окон лимита и переключения аккаунтов за сутки."""

    model_config = ConfigDict(from_attributes=True)

    accounts: list[AccountUsageResponse]
    switches_24h: int


class VolumeUsageResponse(BaseModel):
    name: Volume
    size_bytes: int | None


class DiskUsageResponse(BaseModel):
    """Раздел 15.5: размеры volume по последнему замеру, база и свободное место."""

    volumes: list[VolumeUsageResponse]
    measured_at: datetime | None
    database_bytes: int
    free_bytes: int | None
    total_bytes: int | None


class ContainerResponse(BaseModel):
    """Раздел 15.5: контейнер сессии или script-ноды; `orphaned` — как у уборки (16.2)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    kind: ContainerKind
    task_id: uuid.UUID | None
    task_code: str | None
    started_at: datetime | None
    orphaned: bool
