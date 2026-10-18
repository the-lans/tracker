"""Таблицы `tasks`, `task_repositories` (раздел 3.1 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import (
    MergeStatus,
    PermissionMode,
    RemoteControlStatus,
    RepositoryRole,
    TaskStatus,
)
from db.models.mixins import CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin, pg_enum

_DEFAULT_REMOTE_CONTROL_RECONNECT_ATTEMPTS = 0


class Task(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "tasks"

    code: Mapped[str] = mapped_column(sa.String, unique=True)
    title: Mapped[str] = mapped_column(sa.String)
    description: Mapped[str] = mapped_column(sa.Text)
    guide_url: Mapped[str | None] = mapped_column(sa.String)
    status: Mapped[TaskStatus] = mapped_column(
        pg_enum(TaskStatus, name="task_status"),
        default=TaskStatus.NEW,
    )
    # NULL до атомарной привязки пайплайна (создание task_nodes + заполнение
    # этого поля — одна транзакция, правило 3.2/10 ТЗ).
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("pipelines.id"))
    llm_account_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("llm_accounts.id"))
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("tasks.id"))
    use_parent_summary: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    session_id: Mapped[str | None] = mapped_column(sa.String)
    # NULL, пока не создана активная сессия (раздел 6.1) — до этого момента
    # режима разрешений ещё не существует.
    current_permission_mode: Mapped[PermissionMode | None] = mapped_column(
        pg_enum(PermissionMode, name="permission_mode"),
    )
    auto_accept_plan: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    remote_control_status: Mapped[RemoteControlStatus] = mapped_column(
        pg_enum(RemoteControlStatus, name="remote_control_status"),
        default=RemoteControlStatus.DISCONNECTED,
    )
    remote_control_last_check_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
    )
    remote_control_reconnect_attempts: Mapped[int] = mapped_column(
        sa.Integer,
        default=_DEFAULT_REMOTE_CONTROL_RECONNECT_ATTEMPTS,
    )
    scheduled_start_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    auto_start_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    last_failed_order_index: Mapped[int | None] = mapped_column(sa.Integer)
    repo_cleaned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))


class TaskRepository(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_repositories"

    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"))
    repository_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("repositories.id"))
    role: Mapped[RepositoryRole] = mapped_column(pg_enum(RepositoryRole, name="repository_role"))
    branch_name: Mapped[str] = mapped_column(sa.String)
    base_branch: Mapped[str] = mapped_column(sa.String)
    pushed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    merge_status: Mapped[MergeStatus] = mapped_column(
        pg_enum(MergeStatus, name="merge_status"),
        default=MergeStatus.NOT_PUSHED,
    )
