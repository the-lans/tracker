"""
Нода пайплайна со ссылкой на промт библиотеки (раздел 7.6 ТЗ).

Нода хранит только ссылку (`nodes.library_node_id`) и строку аргументов —
текст, скрипт и гайд при каждом запуске берутся из элемента библиотеки, а
уровень рассуждений остаётся своим, таймаут и retry берутся из системных настроек.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeType
from db.models.pipelines import Node
from db.models.tasks import Task
from services.command_arguments import CommandArguments, parse_arguments
from services.errors import ConflictError, NotFoundError, ValidationError
from services.template_context import build_task_context
from services.templating import (
    render_arguments,
    validate_task_arguments,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

LINKABLE_NODE_TYPES = frozenset({NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.SCRIPT})
# Поля, которые нода со ссылкой берёт у элемента библиотеки.
CONTENT_FIELDS = (
    "prompt_template",
    "command_invocation",
    "script_language",
    "script_content",
    "docker_image",
    "guide_url",
)
# Раздел 7.6: аргументы скрипту — позиционно и одной строкой, как у команды чата.
COMMAND_ARGUMENTS_ENV = "TRACKER_COMMAND_ARGUMENTS"


@dataclass(frozen=True, slots=True)
class LinkedExecution:
    """
    Что выполняется вместо ноды со ссылкой: ``node`` — несохраняемая копия
    ноды с содержимым элемента библиотеки, ``revision`` — его версия.
    """

    node: Node
    arguments: CommandArguments | None = None
    revision: int | None = None

    @property
    def script_args(self) -> tuple[str, ...]:
        return tuple(self.arguments.values) if self.arguments is not None else ()

    def script_env(self, env: dict[str, str] | None) -> dict[str, str] | None:
        if self.arguments is None or self.node.node_type is not NodeType.SCRIPT:
            return env
        return {**(env or {}), COMMAND_ARGUMENTS_ENV: self.arguments.raw}


def _linked_copy(node: Node, source: Node) -> Node:
    columns = sa.inspect(Node).column_attrs
    values = {column.key: getattr(node, column.key) for column in columns}
    values.update({field: getattr(source, field) for field in CONTENT_FIELDS})
    return Node(**values)


def _resolve_arguments(raw: str, *, source: Node, task: Task) -> CommandArguments:
    validate_task_arguments(raw)
    return render_arguments(raw, name=source.slash_name or "", context=build_task_context(task))


async def resolve_linked_execution(
    db_session: AsyncSession, node: Node, *, task: Task
) -> LinkedExecution:
    """
    Элемент библиотеки перечитывается при каждом запуске: сессия воркера
    живёт долго, а правка в библиотеке должна действовать со следующего запуска.
    """
    if node.library_node_id is None:
        return LinkedExecution(node=node)
    source = await db_session.get(Node, node.library_node_id, populate_existing=True)
    if source is None:
        raise NotFoundError(f"Промт библиотеки {node.library_node_id} не найден")
    if node.library_plan_mode and source.node_type is not NodeType.PLAIN_PROMPT:
        raise ValidationError("Промт библиотеки для планирования должен оставаться текстовым")
    arguments = _resolve_arguments(node.library_arguments or "", source=source, task=task)
    return LinkedExecution(
        node=_linked_copy(node, source),
        arguments=arguments,
        revision=source.revision,
    )


def _ensure_linkable(node: Node, source: Node) -> None:
    if not source.is_library_item:
        raise ValidationError("Ссылаться можно только на промт библиотеки")
    if source.is_archived:
        raise ConflictError("Промт в архиве — сослаться на него нельзя")
    if source.node_type not in LINKABLE_NODE_TYPES:
        raise ValidationError(f"Промт библиотеки типа {source.node_type} нельзя выполнить в ноде")
    # Как у команд чата: библиотеки разных пользователей не смешиваются.
    if source.created_by != node.created_by:
        raise ValidationError("Промт библиотеки должен принадлежать автору пайплайна")


async def attach_library_source(
    db_session: AsyncSession,
    node: Node,
    *,
    library_node_id: uuid.UUID | None,
    arguments: str | None,
    plan_mode: bool | None = None,
) -> None:
    """Задаёт или снимает ссылку ноды пайплайна на промт библиотеки."""
    enabled = node.library_plan_mode if plan_mode is None else plan_mode
    if library_node_id is None:
        if plan_mode:
            raise ValidationError("Режим планирования требует текстовый промт библиотеки")
        if node.library_plan_mode:
            node.node_type = NodeType.PLAIN_PROMPT
        node.library_node_id = None
        node.library_arguments = None
        return
    if node.pipeline_id is None:
        raise ValidationError("Ссылка на промт библиотеки — только у ноды пайплайна")
    source = await db_session.get(
        Node, library_node_id, with_for_update=True, populate_existing=True
    )
    if source is None or source.task_id is not None:
        raise NotFoundError(f"Промт библиотеки {library_node_id} не найден")
    if node.library_node_id != library_node_id:
        _ensure_linkable(node, source)
    if enabled and source.node_type is not NodeType.PLAIN_PROMPT:
        raise ValidationError("Режим планирования доступен только для текстового промта библиотеки")
    if arguments:
        validate_task_arguments(arguments)
        parse_arguments(arguments, name=source.slash_name or "")
    node.library_node_id = library_node_id
    node.library_arguments = arguments or None
    node.node_type = NodeType.PLAN_PROMPT if enabled else source.node_type
    for field in CONTENT_FIELDS:
        setattr(node, field, None)
