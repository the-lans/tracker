"""Таблицы `env_variables`, `task_env_variables` (раздел 3.1, 5, 19.4 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import EnvVariableScope
from db.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class EnvVariable(UUIDPrimaryKeyMixin, Base):
    """Переменная окружения (`{{env.VAR_NAME}}`, раздел 5 ТЗ).

    ``repository_id`` заполнено ровно при ``scope = repository`` — прямое
    следствие описания поля в ТЗ ("Заполняется при scope = repository").
    """

    __tablename__ = "env_variables"
    __table_args__ = (
        sa.CheckConstraint(
            "(scope = 'global' AND repository_id IS NULL) "
            "OR (scope = 'repository' AND repository_id IS NOT NULL)",
            name="ck_env_variables_scope_matches_repository_id",
        ),
    )

    key: Mapped[str] = mapped_column(sa.String)
    value_encrypted: Mapped[str] = mapped_column(sa.Text)
    is_secret: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    scope: Mapped[EnvVariableScope] = mapped_column(
        pg_enum(EnvVariableScope, name="env_variable_scope"),
    )
    repository_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("repositories.id"))


class TaskEnvVariable(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_env_variables"

    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"))
    key: Mapped[str] = mapped_column(sa.String)
    value_encrypted: Mapped[str] = mapped_column(sa.Text)
