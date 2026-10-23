"""Таблицы `users`, `allowed_emails` (раздел 3.1, 19.1 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import UserRole
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String, unique=True)
    # Логин SFTP-шлюза (раздел 3.1, решение №18 плана) — не Linux-логин:
    # назначается админом после регистрации через Google OAuth, поэтому nullable.
    os_username: Mapped[str | None] = mapped_column(sa.String, unique=True)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, name="user_role"),
        default=UserRole.USER,
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Раздел 15.1: публичный ключ входа в SFTP-шлюз (не секрет — правило 8 не
    # применяется); действует сразу после сохранения в профиле.
    ssh_public_key: Mapped[str | None] = mapped_column(sa.Text)
    # Раздел 16.2: последний вход по ключу — по нему `revoke_stale_sshfs_keys`
    # находит неиспользуемые ключи; смена ключа сбрасывает значение.
    ssh_key_last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Раздел 15.6: личное подключение к Jira для импорта задач. С email — Jira
    # Cloud (Basic), без него — Server/Data Center (Bearer); токен — секрет.
    jira_url: Mapped[str | None] = mapped_column(sa.String)
    jira_email: Mapped[str | None] = mapped_column(sa.String)
    jira_token_encrypted: Mapped[str | None] = mapped_column(sa.Text)


class AllowedEmail(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "allowed_emails"

    email: Mapped[str] = mapped_column(sa.String, unique=True)
    # NULL — запись создана до появления первого пользователя (bootstrap
    # allowlist из конфигурации/миграции), а не через админ-раздел.
    added_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
