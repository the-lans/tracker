"""Enum-значения полей моделей (раздел 3.1 ТЗ), сгруппированы по таблице.

Значения — snake_case (см. CLAUDE.md, раздел 5), кроме ``PermissionMode``:
``acceptEdits``/``bypassPermissions`` — это литеральные значения режимов
разрешений Claude Agent SDK (раздел 9.3 ТЗ), не выбор проекта — изменить их
регистр означало бы разойтись с самим SDK.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class TaskStatus(StrEnum):
    NEW = "new"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    # Решение 2026-10-19 (отклонение от раздела 3.1): «Приостановить» из
    # раздела 14.2 — отдельный статус, сессия при этом удерживается.
    PAUSED = "paused"
    PLAN_REVIEW = "plan_review"
    AWAITING_INPUT = "awaiting_input"
    REBASE_CONFLICT = "rebase_conflict"
    FAILED = "failed"
    DONE = "done"


class PermissionMode(StrEnum):
    PLAN = "plan"
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS_PERMISSIONS = "bypassPermissions"


class RemoteControlStatus(StrEnum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class RepositoryRole(StrEnum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"


class MergeStatus(StrEnum):
    NOT_PUSHED = "not_pushed"
    PUSHED = "pushed"
    MERGED = "merged"
    CONFLICT = "conflict"


class NodeType(StrEnum):
    PLAIN_PROMPT = "plain_prompt"
    SLASH_COMMAND = "slash_command"
    SCRIPT = "script"
    CLEAR_CONTEXT = "clear_context"
    PLAN_PROMPT = "plan_prompt"


class ScriptLanguage(StrEnum):
    PYTHON = "python"
    BASH = "bash"


class LibraryPromptRunStatus(StrEnum):
    NEVER_RUN = "never_run"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    STOPPED = "stopped"


class ManualRequestType(StrEnum):
    LIBRARY_PROMPT = "library_prompt"
    FREEFORM_PROMPT = "freeform_prompt"
    # Пересказ истории для дочерней задачи (`use_parent_summary`): ставится в
    # очередь родителя, пока его сессией владеет воркер.
    PARENT_SUMMARY = "parent_summary"


class ManualRequestStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    CANCELLED = "cancelled"


class NodeLogTriggerType(StrEnum):
    PIPELINE = "pipeline"
    LIBRARY_MANUAL = "library_manual"
    FREEFORM_MANUAL = "freeform_manual"
    # Лента родителя: его сессия пересказывает историю для дочерней задачи.
    SUMMARY_FOR_CHILD = "summary_for_child"
    # Лента дочерней задачи: пересказ родителя — первый ход её новой сессии.
    PARENT_SUMMARY = "parent_summary"


class ParentSummaryStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    UNAVAILABLE = "unavailable"


class NodeLogStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_DECISION = "awaiting_decision"
    SUCCESS = "success"
    FAILED = "failed"
    STOPPED = "stopped"


class AppLogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LlmAccountStatus(StrEnum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"


class EnvVariableScope(StrEnum):
    GLOBAL = "global"
    REPOSITORY = "repository"


class McpAuthType(StrEnum):
    """Тип авторизации MCP-сервера.

    ТЗ (раздел 3.1, таблица ``mcp_servers``) объявляет поле как ``enum`` без
    перечисления значений. Набор ниже — минимальный, покрывающий типовые
    схемы авторизации HTTP-based MCP-серверов; расширяется по мере
    появления реальных серверов, требующих иного механизма.
    """

    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"


class McpIsolationMode(StrEnum):
    NONE = "none"
    ISOLATED_FLAG = "isolated_flag"
    PER_TASK_DATA_DIR = "per_task_data_dir"


class PeriodicScheduleType(StrEnum):
    INTERVAL = "interval"
    CRONTAB = "crontab"


class PeriodicRunStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"
