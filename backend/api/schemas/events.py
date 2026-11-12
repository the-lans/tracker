"""Лента событий (раздел 18.4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from db.models.enums import EventAudience, EventCategory


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    audience: EventAudience
    category: EventCategory
    event_type: str
    title: str
    body: str
    task_id: uuid.UUID | None
