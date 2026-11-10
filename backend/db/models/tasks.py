"""Таблицы `tasks`, `task_repositories` (раздел 3.1 ТЗ), `task_parent_summaries`."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import (
    MergeStatus,
    ParentSummaryStatus,
    PermissionMode,
    RemoteControlStatus,
    RepositoryRole,
    TaskStatus,
)
from db.models.mixins import (
    CreatedAtMixin,
    CreatedUpdatedAtMixin,
    UUIDPrimaryKeyMixin,
    pg_enum,
)

_DEFAULT_REMOTE_CONTROL_RECONNECT_ATTEMPTS = 0
# Раздел 14.4: ручной приоритет в очереди пользователя — больше раньше.
DEFAULT_QUEUE_PRIORITY = 100
MIN_QUEUE_PRIORITY = 1
MAX_QUEUE_PRIORITY = 1_000_000


class Task(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        sa.CheckConstraint(
            f"queue_priority BETWEEN {MIN_QUEUE_PRIORITY} AND {MAX_QUEUE_PRIORITY}",
            name="ck_tasks_queue_priority",
        ),
        sa.Index(
            "ix_tasks_queue",
            "created_by",
            "status",
            sa.text("queue_priority DESC"),
            "ready_at",
        ),
    )

    code: Mapped[str] = mapped_column(sa.String, unique=True)
    title: Mapped[str] = mapped_column(sa.String)
    description: Mapped[str] = mapped_column(sa.Text)
    guide_url: Mapped[str | None] = mapped_column(sa.String)
    # Раздел 15.6: задача Jira, из которой задача импортирована.
    jira_issue_url: Mapped[str | None] = mapped_column(sa.String)
    status: Mapped[TaskStatus] = mapped_column(
        pg_enum(TaskStatus, name="task_status"),
        default=TaskStatus.NEW,
    )
    # NULL до атомарной привязки пайплайна (создание task_nodes + заполнение
    # этого поля — одна транзакция, правило 3.2/10 ТЗ).
    manual_requests_closed: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("pipelines.id"))
    # Стартовый аккаунт задачи; дальше воркер переключает аккаунт сам (раздел 19.7).
    llm_account_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("llm_accounts.id"))
    # Аккаунт последнего обращения к модели — выставляет воркер перед каждым обращением.
    current_llm_account_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("llm_accounts.id"),
    )
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
        # Раздел 6.3: мост через LLM-прокси невозможен.
        default=RemoteControlStatus.UNAVAILABLE,
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
    # Раздел 14.2 «Вернуть в новые»: выполнения нод до этого момента не
    # учитываются ни точкой перезапуска, ни переходом в `done`.
    reset_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Раздел 5 `{{node.llm_output_last_n}}`: реплики до этого момента —
    # прежней сессии (очистка контекста, смена LLM-аккаунта).
    context_cleared_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    repo_cleaned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Раздел 14.4: очередь автора — `ready`/`night_worker` по приоритету, затем
    # по времени постановки; слот ручного запуска и чата — по `occupies_slot`.
    queue_priority: Mapped[int] = mapped_column(
        sa.Integer,
        default=DEFAULT_QUEUE_PRIORITY,
        server_default=str(DEFAULT_QUEUE_PRIORITY),
    )
    ready_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    occupies_slot: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    launched_manually: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    # «Отменить постановку» возвращает задачу в статус, из которого она ушла в `queued`.
    queued_from_status: Mapped[TaskStatus | None] = mapped_column(
        pg_enum(TaskStatus, name="task_status"),
    )
    # Раздел 14.4: воркер ведёт чат задачи в «Уточняется» (в том числе пока
    # агент ждёт ответа) — по нему сбой воркера возвращает задачу в `refining`.
    chat_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    # Раздел 19.7: ожидание сброса лимита — статус, в который задача вернётся,
    # когда продолжит, и нода, с которой продолжит.
    limit_wait_from_status: Mapped[TaskStatus | None] = mapped_column(
        pg_enum(TaskStatus, name="task_status"),
    )
    limit_wait_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    limit_wait_order_index: Mapped[int | None] = mapped_column(sa.Integer)
    # Попытка ноды, ждавшей сброса: после него повторы продолжают счёт с неё.
    limit_wait_attempt: Mapped[int | None] = mapped_column(sa.Integer)
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
    # Раздел 16.2: ветку родителя слили — ребейз на новую базу выполнит воркер
    # задачи в ближайшей точке между нодами и очистит отметку.
    rebase_requested_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TaskParentSummary(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """
    Пересказ истории родителя для дочерней задачи (`tasks.use_parent_summary`).

    Отдельный артефакт, а не реплика в `node_logs`: его составляет сессия
    родителя, а получает первым сообщением новая сессия дочерней задачи.
    Одна запись на дочернюю задачу — повторный запуск не просит пересказ снова.
    """

    __tablename__ = "task_parent_summaries"

    parent_task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"))
    child_task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"), unique=True)
    status: Mapped[ParentSummaryStatus] = mapped_column(
        pg_enum(ParentSummaryStatus, name="parent_summary_status"),
        default=ParentSummaryStatus.PENDING,
    )
    summary_text: Mapped[str | None] = mapped_column(sa.Text)
    unavailable_reason: Mapped[str | None] = mapped_column(sa.Text)
    # Запрос в очереди родителя, если его сессия была занята; NULL — пересказ
    # делается в ответвлении сессии родителя.
    manual_request_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("task_manual_request_queue.id"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
