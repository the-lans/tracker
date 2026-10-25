"""
Пайплайны, ноды и библиотека промтов, предпросмотр шаблона (раздел 3.1, 5, 7.2, 13).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from api.schemas.common import MaxRetries, RetryBaseDelaySeconds, TimeoutSeconds
from db.models.enums import (
    NodeType,
    ScriptLanguage,
)


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
    created_by: uuid.UUID


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
    # Раздел 15.5: не переданные значения берутся из «Системных настроек».
    timeout_seconds: TimeoutSeconds | None = None
    max_retries: MaxRetries | None = None
    retry_base_delay_seconds: RetryBaseDelaySeconds | None = None
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
    timeout_seconds: TimeoutSeconds | None = None
    max_retries: MaxRetries | None = None
    retry_base_delay_seconds: RetryBaseDelaySeconds | None = None
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
    created_by: uuid.UUID


class TemplatePreviewRequest(BaseModel):
    """Раздел 5.1: предпросмотр рендеринга — одна функция на все три места
    ввода (конструктор пайплайна, библиотека, свободный промт), различаемые
    ``scope``."""

    text: str
    scope: str
    task_id: uuid.UUID | None = None
    # Только для `scope = pipeline`: позиция ноды задаёт доступные `{{node.*}}`.
    # У сохранённой ноды пайплайн и позиция берутся из `node_id`, у новой —
    # из `pipeline_id`/`order_index`.
    node_id: uuid.UUID | None = None
    pipeline_id: uuid.UUID | None = None
    order_index: int | None = Field(default=None, ge=0)


class TemplatePreviewResponse(BaseModel):
    rendered_text: str
