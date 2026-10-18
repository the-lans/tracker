"""Переиспользуемые колонки моделей."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column


def pg_enum(enum_cls: type[Enum], *, name: str) -> sa.Enum:
    """Postgres enum-тип, хранящий ``.value`` элементов, а не ``.name``."""
    return sa.Enum(enum_cls, name=name, values_callable=lambda cls: [item.value for item in cls])


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        primary_key=True,
        default=uuid.uuid4,
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )


class CreatedUpdatedAtMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


# Заглушка типа для mypy strict в местах, где jsonb-колонка хранит
# произвольную (валидируемую на уровне services/) структуру.
JsonValue = dict[str, Any]
