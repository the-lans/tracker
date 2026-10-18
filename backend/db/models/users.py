"""Таблицы `users`, `allowed_emails` (раздел 3.1, 19.1 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import UserRole
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String, unique=True)
    # os_username ссылается на уже существующий, вручную настроенный
    # Linux-логин (провижининг вне периметра проекта) — заполняется админом
    # после регистрации через Google OAuth, поэтому nullable.
    os_username: Mapped[str | None] = mapped_column(sa.String, unique=True)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, name="user_role"),
        default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)


class AllowedEmail(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "allowed_emails"

    email: Mapped[str] = mapped_column(sa.String, unique=True)
    # NULL — запись создана до появления первого пользователя (bootstrap
    # allowlist из конфигурации/миграции), а не через админ-раздел.
    added_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
