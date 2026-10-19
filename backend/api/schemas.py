"""Общие Pydantic-схемы запросов/ответов REST API (раздел 2.3, 2.4 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from db.models.enums import (
    AppLogLevel,
    EnvVariableScope,
    LibraryPromptRunStatus,
    LlmAccountStatus,
    ManualRequestStatus,
    ManualRequestType,
    McpAuthType,
    McpIsolationMode,
    MergeStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    PeriodicRunStatus,
    PeriodicScheduleType,
    PermissionMode,
    RemoteControlStatus,
    RepositoryRole,
    ScriptLanguage,
    TaskStatus,
    UserRole,
)


class AwaitingDecisionCountResponse(BaseModel):
    """Раздел 18.3: счётчик задач, ожидающих решения, в постоянной навигации."""

    count: int


class TaskRepositoryAttachRequest(BaseModel):
    """Раздел 1.2 (сценарий 1): репозиторий задачи и его роль."""

    repository_id: uuid.UUID
    role: RepositoryRole
    base_branch: str = "main"


class TaskCreateRequest(BaseModel):
    code: str
    title: str
    description: str
    guide_url: str | None = None
    parent_task_id: uuid.UUID | None = None
    use_parent_summary: bool = False
    llm_account_id: uuid.UUID | None = None
    repositories: list[TaskRepositoryAttachRequest] = []


class TaskUpdateRequest(BaseModel):
    """Поля задачи, редактируемые после создания (раздел 12.1, 14.2).

    ``auto_accept_plan`` меняется в любой момент до `done` (раздел 15.2);
    остальные — только пока задача в статусе `new`.
    """

    title: str | None = None
    description: str | None = None
    guide_url: str | None = None
    llm_account_id: uuid.UUID | None = None
    auto_start_enabled: bool | None = None
    scheduled_start_at: datetime | None = None
    auto_accept_plan: bool | None = None


class TaskRepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    role: RepositoryRole
    branch_name: str
    base_branch: str
    pushed_at: datetime | None
    merge_status: MergeStatus


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    description: str
    guide_url: str | None
    status: TaskStatus
    pipeline_id: uuid.UUID | None
    llm_account_id: uuid.UUID | None
    parent_task_id: uuid.UUID | None
    session_id: str | None
    current_permission_mode: PermissionMode | None
    auto_accept_plan: bool
    remote_control_status: RemoteControlStatus
    scheduled_start_at: datetime | None
    auto_start_enabled: bool
    last_failed_order_index: int | None
    created_at: datetime
    updated_at: datetime


class BindPipelineRequest(BaseModel):
    pipeline_id: uuid.UUID


class NodeLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID | None
    trigger_type: NodeLogTriggerType
    attempt_number: int
    rendered_prompt: str | None
    llm_output_text: str | None
    user_input_text: str | None
    script_stdout: str | None
    script_exit_code: int | None
    status: NodeLogStatus
    pending_question: str | None
    pending_plan_text: str | None
    pending_options: list[dict[str, str]] | None
    started_at: datetime | None
    finished_at: datetime | None


class DecisionRequest(BaseModel):
    """Раздел 9.6: ответ на `awaiting_input`/`plan_review`.

    ``option_id`` — выбор одной из `pending_options` (включая варианты
    решения по плану, раздел 9.3); ``feedback_text`` — свободный текст,
    обязателен для "Доработать план" (раздел 9.3), опционален для прочих.
    """

    node_log_id: uuid.UUID
    option_id: str
    feedback_text: str | None = None


class FreeformPromptRequest(BaseModel):
    raw_prompt_text: str


class LibraryPromptAddRequest(BaseModel):
    node_id: uuid.UUID


class TaskLibraryPromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    last_run_status: LibraryPromptRunStatus
    last_run_at: datetime | None


class TaskLibraryPromptListItem(TaskLibraryPromptResponse):
    """Строка таблицы «Системные промты задачи» (раздел 15.2): кнопка ■
    останавливает ``active_request_id`` — запрос в очереди или в работе."""

    name: str
    node_type: NodeType
    active_request_id: uuid.UUID | None


class ManualRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_type: ManualRequestType
    node_id: uuid.UUID | None
    raw_prompt_text: str | None
    status: ManualRequestStatus
    requested_at: datetime


class TaskNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    order_index: int
    is_enabled: bool
    name: str
    node_type: NodeType
    editable: bool


class TaskNodeUpdateRequest(BaseModel):
    is_enabled: bool


# --- Репозитории и шаблоны (раздел 3.1) --------------------------------


class RepositoryCreateRequest(BaseModel):
    name: str
    git_url: str
    default_template_id: uuid.UUID | None = None
    deploy_key: str


class RepositoryUpdateRequest(BaseModel):
    name: str | None = None
    git_url: str | None = None
    default_template_id: uuid.UUID | None = None
    deploy_key: str | None = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_url: str
    default_template_id: uuid.UUID | None


class TemplateCreateRequest(BaseModel):
    name: str
    files: dict[str, Any]
    mcp_server_ids: list[uuid.UUID] = []


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    files: dict[str, Any] | None = None
    mcp_server_ids: list[uuid.UUID] | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    files: dict[str, Any]
    mcp_server_ids: list[uuid.UUID]


# --- LLM-аккаунты (раздел 3.1) ------------------------------------------


class LlmAccountCreateRequest(BaseModel):
    label: str
    claude_config_dir: str
    status: LlmAccountStatus = LlmAccountStatus.ACTIVE


class LlmAccountUpdateRequest(BaseModel):
    label: str | None = None
    claude_config_dir: str | None = None
    status: LlmAccountStatus | None = None


class LlmAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    claude_config_dir: str
    status: LlmAccountStatus


# --- Переменные окружения (раздел 3.1, 5, 19.4) -------------------------


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


# --- MCP-серверы (раздел 3.1, 10.2) --------------------------------------


class McpServerCreateRequest(BaseModel):
    name: str
    url: str
    auth_type: McpAuthType
    auth_config: str
    has_stateful_resource: bool = False
    isolation_mode: McpIsolationMode | None = None
    isolation_path_template: str | None = None


class McpServerUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    auth_type: McpAuthType | None = None
    auth_config: str | None = None
    has_stateful_resource: bool | None = None
    isolation_mode: McpIsolationMode | None = None
    isolation_path_template: str | None = None


class McpServerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    auth_type: McpAuthType
    is_healthy: bool
    has_stateful_resource: bool
    isolation_mode: McpIsolationMode | None
    isolation_path_template: str | None


# --- Пайплайны и ноды/библиотека промтов (раздел 3.1, 7.2, 13) ---------


class PipelineCreateRequest(BaseModel):
    name: str


class PipelineUpdateRequest(BaseModel):
    name: str | None = None
    is_archived: bool | None = None


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_archived: bool


class NodeCreateRequest(BaseModel):
    """Раздел 3.1: одна и та же форма для ноды пайплайна и промта
    библиотеки — различие только в ``pipeline_id``/``order_index``
    (заполнены для ноды пайплайна, пусты для библиотечного промта,
    раздел 15.4 ТЗ)."""

    pipeline_id: uuid.UUID | None = None
    order_index: int | None = None
    name: str
    description: str | None = None
    node_type: NodeType
    prompt_template: str | None = None
    command_invocation: str | None = None
    script_language: ScriptLanguage | None = None
    script_content: str | None = None
    docker_image: str | None = None
    timeout_seconds: int = 600
    max_retries: int = 3
    retry_base_delay_seconds: int = 5
    guide_url: str | None = None
    is_skipped: bool = False
    llm_output_last_n: int | None = None


class NodeUpdateRequest(BaseModel):
    order_index: int | None = None
    name: str | None = None
    description: str | None = None
    prompt_template: str | None = None
    command_invocation: str | None = None
    script_language: ScriptLanguage | None = None
    script_content: str | None = None
    docker_image: str | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    retry_base_delay_seconds: int | None = None
    guide_url: str | None = None
    is_skipped: bool | None = None
    is_archived: bool | None = None
    llm_output_last_n: int | None = None


class NodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pipeline_id: uuid.UUID | None
    order_index: int | None
    name: str
    description: str | None
    node_type: NodeType
    prompt_template: str | None
    command_invocation: str | None
    script_language: ScriptLanguage | None
    script_content: str | None
    docker_image: str | None
    timeout_seconds: int
    max_retries: int
    retry_base_delay_seconds: int
    guide_url: str | None
    is_skipped: bool
    is_library_item: bool
    llm_output_last_n: int | None
    is_archived: bool


class TemplatePreviewRequest(BaseModel):
    """Раздел 5.1: предпросмотр рендеринга — одна функция на все три места
    ввода (конструктор пайплайна, библиотека, свободный промт), различаемые
    ``scope``."""

    text: str
    scope: str
    task_id: uuid.UUID | None = None
    node_id: uuid.UUID | None = None


class TemplatePreviewResponse(BaseModel):
    rendered_text: str


# --- Административная часть (раздел 15.5, 19.1, 19.2) --------------------


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    os_username: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    os_username: str | None = None


class AllowedEmailCreateRequest(BaseModel):
    email: str


class AllowedEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    added_by: uuid.UUID | None
    created_at: datetime


class PeriodicTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str
    task_path: str
    schedule_type: PeriodicScheduleType
    interval_seconds: int | None
    crontab_expression: str | None
    is_enabled: bool
    last_run_at: datetime | None
    last_run_status: PeriodicRunStatus | None
    next_run_at: datetime | None


class PeriodicTaskUpdateRequest(BaseModel):
    """Раздел 16.1: расписание редактируется без перезапуска процессов —
    ровно одно из двух полей заполнено, в соответствии с `schedule_type`
    текущей записи (менять сам `schedule_type` не поддерживается — это
    сменило бы природу задачи, не просто её расписание)."""

    interval_seconds: int | None = None
    crontab_expression: str | None = None
    is_enabled: bool | None = None


# --- Web Push (раздел 18.1) ----------------------------------------------


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    """Форма `PushSubscriptionJSON` стандарта Push API — то, что отдаёт
    `PushSubscription.toJSON()` в браузере."""

    endpoint: str
    keys: PushSubscriptionKeys


class VapidPublicKeyResponse(BaseModel):
    public_key: str


class AppLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    level: AppLogLevel
    source: str
    message: str
    context: dict[str, Any]
    task_id: uuid.UUID | None
    created_at: datetime
