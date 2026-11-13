"""Категории задач (раздел 15.7 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from db.models.tasks import DEFAULT_QUEUE_PRIORITY, MAX_QUEUE_PRIORITY, MIN_QUEUE_PRIORITY


class TaskCategoryRequest(BaseModel):
    """Создание и правка категории — форма целиком."""

    name: str = Field(min_length=1)
    pipeline_id: uuid.UUID | None = None
    auto_accept_plan: bool = False
    library_prompt_ids: list[uuid.UUID] = []
    queue_priority: int = Field(
        DEFAULT_QUEUE_PRIORITY,
        ge=MIN_QUEUE_PRIORITY,
        le=MAX_QUEUE_PRIORITY,
    )
    occupies_slot: bool = False


class TaskCategoryResponse(BaseModel):
    id: uuid.UUID
    name: str
    pipeline_id: uuid.UUID | None
    auto_accept_plan: bool
    library_prompt_ids: list[uuid.UUID]
    queue_priority: int
    occupies_slot: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
