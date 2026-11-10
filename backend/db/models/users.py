"""Таблицы `users`, `allowed_emails` (раздел 3.1, 19.1 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import UserRole
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum

# Раздел 19.7: порог расхода 5-часового окна, после которого аккаунт задачи не берут.
DEFAULT_LLM_SWITCH_THRESHOLD_PCT = 93
MIN_LLM_SWITCH_THRESHOLD_PCT = 1
MAX_LLM_SWITCH_THRESHOLD_PCT = 100
_THRESHOLD_RANGE = f"BETWEEN {MIN_LLM_SWITCH_THRESHOLD_PCT} AND {MAX_LLM_SWITCH_THRESHOLD_PCT}"
# Раздел 14.4: слоты параллельного запуска задач пользователя.
DEFAULT_MAX_PARALLEL_TASKS = 3
MIN_MAX_PARALLEL_TASKS = 1
MAX_MAX_PARALLEL_TASKS = 50


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint(
            f"llm_switch_threshold_5h_pct {_THRESHOLD_RANGE}",
            name="ck_users_llm_switch_threshold_5h_pct",
        ),
        sa.CheckConstraint(
            f"max_parallel_tasks BETWEEN {MIN_MAX_PARALLEL_TASKS} AND {MAX_MAX_PARALLEL_TASKS}",
            name="ck_users_max_parallel_tasks",
        ),
    )

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
    # Раздел 15.6: личный доступ к Jira для импорта задач (адрес Jira — системная
    # настройка). С email — Jira Cloud (Basic), без него — Server/Data Center
    # (Bearer); токен — секрет.
    jira_email: Mapped[str | None] = mapped_column(sa.String)
    jira_token_encrypted: Mapped[str | None] = mapped_column(sa.Text)
    llm_switch_threshold_5h_pct: Mapped[int] = mapped_column(
        sa.Integer,
        default=DEFAULT_LLM_SWITCH_THRESHOLD_PCT,
        server_default=str(DEFAULT_LLM_SWITCH_THRESHOLD_PCT),
    )
    # Недельного порога нет: `llm_switch_threshold_week_pct` остаётся в БД для
    # прежней версии (раздел 20.6) и не отображается.
    llm_compact_on_switch: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=True,
        server_default=sa.true(),
    )
    max_parallel_tasks: Mapped[int] = mapped_column(
        sa.Integer,
        default=DEFAULT_MAX_PARALLEL_TASKS,
        server_default=str(DEFAULT_MAX_PARALLEL_TASKS),
    )


class AllowedEmail(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "allowed_emails"

    email: Mapped[str] = mapped_column(sa.String, unique=True)
    # NULL — запись создана до появления первого пользователя (bootstrap
    # allowlist из конфигурации/миграции), а не через админ-раздел.
    added_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
