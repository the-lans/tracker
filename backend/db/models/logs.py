"""Таблицы `node_logs`, `app_logs` (раздел 3.1, 17.2 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import (
    AppLogLevel,
    LlmSwitchReason,
    NodeLogStatus,
    NodeLogTriggerType,
    ReasoningEffort,
)
from db.models.mixins import JsonValue, UUIDPrimaryKeyMixin, pg_enum

_DEFAULT_ATTEMPT_NUMBER = 1


class NodeLog(UUIDPrimaryKeyMixin, Base):
    """Единая история выполнения — каждая отправка в сессию/запуск скрипта (3.1)."""

    __tablename__ = "node_logs"

    command_name: Mapped[str | None] = mapped_column(sa.String(64))
    command_revision: Mapped[int | None] = mapped_column(sa.Integer)
    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"))
    # NULL — запись соответствует свободному промту без сохранения в библиотеку.
    node_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("nodes.id"))
    trigger_type: Mapped[NodeLogTriggerType] = mapped_column(
        pg_enum(NodeLogTriggerType, name="node_log_trigger_type"),
    )
    attempt_number: Mapped[int] = mapped_column(sa.Integer, default=_DEFAULT_ATTEMPT_NUMBER)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"))
    rendered_prompt: Mapped[str | None] = mapped_column(sa.Text)
    llm_output_text: Mapped[str | None] = mapped_column(sa.Text)
    user_input_text: Mapped[str | None] = mapped_column(sa.Text)
    # Длина `llm_output_text` в момент запроса решения (раздел 15.2): там лента
    # показывает решение пользователя.
    decision_output_offset: Mapped[int | None] = mapped_column(sa.Integer)
    script_stdout: Mapped[str | None] = mapped_column(sa.Text)
    script_exit_code: Mapped[int | None] = mapped_column(sa.Integer)
    # Причина `failed` для ленты (раздел 15.2): таймаут, ошибка сессии и т. п.
    error_message: Mapped[str | None] = mapped_column(sa.Text)
    # Раздел 19.7: аккаунт, модель и уровень (на шкале провайдера) обращения к модели.
    llm_account_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("llm_accounts.id"),
        index=True,
    )
    llm_model: Mapped[str | None] = mapped_column(sa.String)
    reasoning_effort: Mapped[ReasoningEffort | None] = mapped_column(
        pg_enum(ReasoningEffort, name="reasoning_effort"),
    )
    # Раздел 15.2: почему обращение ушло не на аккаунт прежнего обращения.
    llm_switch_reason: Mapped[LlmSwitchReason | None] = mapped_column(
        pg_enum(LlmSwitchReason, name="llm_switch_reason"),
    )
    # Раздел 19.7: перед обращением контекст сессии сжат `/compact` при смене аккаунта.
    llm_context_compacted: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    status: Mapped[NodeLogStatus] = mapped_column(
        pg_enum(NodeLogStatus, name="node_log_status"),
        default=NodeLogStatus.PENDING,
    )
    pending_question: Mapped[str | None] = mapped_column(sa.Text)
    pending_plan_text: Mapped[str | None] = mapped_column(sa.Text)
    # Массив вариантов ответа [{"id": "...", "label": "..."}] (раздел 9.6).
    pending_options: Mapped[list[JsonValue] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class AppLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "app_logs"

    level: Mapped[AppLogLevel] = mapped_column(pg_enum(AppLogLevel, name="app_log_level"))
    source: Mapped[str] = mapped_column(sa.String)
    message: Mapped[str] = mapped_column(sa.Text)
    context: Mapped[JsonValue] = mapped_column(JSONB, default=dict)
    task_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("tasks.id"))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
