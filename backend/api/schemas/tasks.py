"""
Задачи: создание, карточка, ноды, история, решения, ручные запросы,
артефакты (раздел 2.3, 7, 8, 9.6, 13, 14.3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from db.models.enums import (
    LibraryPromptRunStatus,
    ManualRequestStatus,
    ManualRequestType,
    MergeStatus,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    PermissionMode,
    RemoteControlStatus,
    RepositoryRole,
    TaskStatus,
)


class AwaitingDecisionCountResponse(BaseModel):
    """Раздел 18.3: счётчик задач, ожидающих решения, в постоянной навигации."""

    count: int


class TaskRepositoryAttachRequest(BaseModel):
    """Раздел 1.2 (сценарий 1): репозиторий задачи и его роль."""

    repository_id: uuid.UUID
    role: RepositoryRole
    base_branch: str = "main"


class TaskDuplicateRequest(BaseModel):
    """Раздел 14.2 «Дублировать задачу»: форма создания с новым кодом."""

    code: str
    title: str
    description: str
    guide_url: str | None = None
    llm_account_id: uuid.UUID | None = None
    repositories: list[TaskRepositoryAttachRequest] = []


class TaskCreateRequest(TaskDuplicateRequest):
    parent_task_id: uuid.UUID | None = None
    use_parent_summary: bool = False
    # Раздел 15.6: задача заполнена из Jira — ссылка и вложения берутся по ключу.
    jira_issue_key: str | None = None


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
    jira_issue_url: str | None = None
    status: TaskStatus
    pipeline_id: uuid.UUID | None
    llm_account_id: uuid.UUID | None
    parent_task_id: uuid.UUID | None
    use_parent_summary: bool
    session_id: str | None
    current_permission_mode: PermissionMode | None
    auto_accept_plan: bool
    remote_control_status: RemoteControlStatus
    scheduled_start_at: datetime | None
    auto_start_enabled: bool
    last_failed_order_index: int | None
    repo_cleaned_at: datetime | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class BindPipelineRequest(BaseModel):
    pipeline_id: uuid.UUID
    # Раздел 13.1: чекбоксы, снятые при выборе пайплайна; `None` — по
    # умолчанию выключены ноды с `is_skipped`.
    disabled_node_ids: list[uuid.UUID] | None = None


class NodeDependentResponse(BaseModel):
    """Раздел 13.3, 15.2: нода, которая берёт вывод у отключаемой."""

    model_config = ConfigDict(from_attributes=True)

    node_id: uuid.UUID
    name: str


class PipelineDependentsRequest(BaseModel):
    node_id: uuid.UUID
    enabled_node_ids: list[uuid.UUID]


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


class ArtifactResponse(BaseModel):
    """
    Раздел 14.3, 15.2: файл артефактов задачи; `path` — относительно её каталога.
    """

    model_config = ConfigDict(from_attributes=True)

    path: str
    size: int
    modified_at: datetime
