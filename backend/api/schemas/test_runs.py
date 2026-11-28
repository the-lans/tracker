"""Профиль Compose и результаты проверок задачи."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from services.test_profile_types import TestProfile as TestProfile


class DetectProfileRequest(BaseModel):
    git_url: str
    git_credential_id: uuid.UUID | None = None
    branch: str = "master"


class StartTestRunRequest(BaseModel):
    repository_id: uuid.UUID
    check: str = Field(min_length=1)
    idempotency_key: uuid.UUID = Field(default_factory=uuid.uuid4)


class TestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    repository_id: uuid.UUID
    check: str
    source: str
    status: str
    cleanup_status: str
    cleanup_error: str | None
    exit_code: int | None
    logs: str = ""
    error: str | None
    report_files: list[str]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
