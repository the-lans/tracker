"""
Переменные окружения системы и задачи (раздел 3.1, 5, 19.4).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from db.models.enums import (
    EnvVariableScope,
)


class EnvVariableCreateRequest(BaseModel):
    key: str
    value: str
    is_secret: bool = False
    scope: EnvVariableScope
    repository_id: uuid.UUID | None = None


class EnvVariableUpdateRequest(BaseModel):
    value: str | None = None
    is_secret: bool | None = None


class EnvVariableResponse(BaseModel):
    """``value`` намеренно отсутствует — раздел 19.4/CLAUDE.md, правило 8:
    "Значения скрыты в UI по умолчанию"; расшифрованное значение отдаётся
    только явным эндпоинтом `.../reveal`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    is_secret: bool
    scope: EnvVariableScope
    repository_id: uuid.UUID | None


class EnvVariableRevealResponse(BaseModel):
    value: str


class TaskEnvVariableCreateRequest(BaseModel):
    key: str
    value: str


class TaskEnvVariableUpdateRequest(BaseModel):
    value: str


class TaskEnvVariableResponse(BaseModel):
    """
    Раздел 15.2: переменная задачи; значение скрыто (правило 8) — только
    через `.../reveal`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
