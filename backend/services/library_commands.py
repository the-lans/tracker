"""
Команды библиотеки пользователя: разрешение, версия и неизменяемый снимок вызова.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app_logging.config import get_logger
from db.models.enums import (
    ManualRequestStatus,
    ManualRequestType,
    NodeType,
    ReasoningEffort,
    ScriptLanguage,
)
from db.models.pipelines import Node
from db.models.prompts import TaskManualRequestQueue
from db.models.tasks import Task
from services.command_arguments import (
    CommandArguments,
    invocation_name,
    parse_invocation,
    prepare_arguments,
)
from services.crypto import decrypt, encrypt
from services.errors import ConflictError, NotFoundError, ValidationError
from services.manual_admission import ensure_manual_requests_open
from services.system_settings import resolve_runner_image
from services.task_launch import ensure_llm_for_request
from services.template_context import RenderedText, render_for_task

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger("library_commands")
COMMAND_TYPES = (NodeType.PLAIN_PROMPT, NodeType.SCRIPT)


class CommandSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation: str
    raw_arguments: str
    arguments: list[str]
    name: str
    node_type: NodeType
    prompt_template: str | None
    script_language: ScriptLanguage | None
    script_content: str | None
    docker_image: str | None
    timeout_seconds: int
    max_retries: int
    retry_base_delay_seconds: int
    llm_output_last_n: int | None
    reasoning_effort: ReasoningEffort | None

    def to_node(self, request: TaskManualRequestQueue) -> Node:
        return Node(
            id=request.node_id,
            created_by=request.requested_by,
            is_library_item=True,
            revision=request.command_revision,
            **self.model_dump(exclude={"invocation", "raw_arguments", "arguments"}),
        )


def validate_command_node(node: Node) -> None:
    if node.slash_name and (
        not node.is_library_item or node.task_id is not None or node.node_type not in COMMAND_TYPES
    ):
        raise ValidationError(
            "Команду можно назначить только текстовому промту или скрипту библиотеки"
        )
    if node.slash_name:
        if node.node_type is NodeType.PLAIN_PROMPT and not (node.prompt_template or "").strip():
            raise ValidationError("Для команды-промта заполните текст промта")
        if node.node_type is NodeType.SCRIPT and (
            node.script_language is None or not (node.script_content or "").strip()
        ):
            raise ValidationError("Для команды-скрипта укажите язык и код скрипта")
    if node.argument_hint and not node.slash_name:
        raise ValidationError("Подсказка аргументов требует имени команды")


async def list_commands(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    prefix: str,
    limit: int,
    offset: int,
) -> Sequence[Node]:
    # Имя пользователя строгое: административный доступ не смешивает библиотеки.
    query = sa.select(Node).where(
        Node.created_by == owner_id,
        Node.is_library_item.is_(True),
        Node.is_archived.is_(False),
        Node.slash_name.is_not(None),
    )
    if prefix:
        query = query.where(
            Node.slash_name.startswith(prefix.lower().removeprefix("/"), autoescape=True)
        )
    return (
        await session.scalars(query.order_by(Node.slash_name).limit(limit).offset(offset))
    ).all()


async def _find_command(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    invocation: str,
    lock: bool = False,
) -> Node:
    query = sa.select(Node).where(
        Node.created_by == owner_id,
        Node.slash_name == invocation_name(invocation),
        Node.is_library_item.is_(True),
        Node.is_archived.is_(False),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    node = await session.scalar(query)
    if node is None:
        raise NotFoundError("Команда не найдена в библиотеке владельца задачи")
    validate_command_node(node)
    return node


async def enqueue_command(
    session: AsyncSession,
    *,
    task: Task,
    requested_by: uuid.UUID,
    invocation: str,
    client_request_id: uuid.UUID,
) -> TaskManualRequestQueue:
    # Блокировка задачи сериализует повторные запросы и запуск/остановку задачи.
    await session.refresh(task, with_for_update=True)
    previous = await session.scalar(
        sa.select(TaskManualRequestQueue).where(
            TaskManualRequestQueue.task_id == task.id,
            TaskManualRequestQueue.requested_by == requested_by,
            TaskManualRequestQueue.client_request_id == client_request_id,
        )
    )
    if previous is not None:
        snapshot = load_snapshot(previous)
        if snapshot.invocation != invocation:
            raise ConflictError("Идентификатор вызова уже использован для другой команды")
        return previous
    ensure_manual_requests_open(task)
    node = await _find_command(session, owner_id=task.created_by, invocation=invocation, lock=True)
    arguments = parse_invocation(invocation)
    await ensure_llm_for_request(
        session,
        task,
        needs_llm=node.node_type is NodeType.PLAIN_PROMPT,
    )
    snapshot = await snapshot_command(
        session, node=node, invocation=invocation, arguments=arguments
    )
    request = TaskManualRequestQueue(
        task_id=task.id,
        requested_by=requested_by,
        node_id=node.id,
        request_type=ManualRequestType.LIBRARY_PROMPT,
        status=ManualRequestStatus.QUEUED,
        command_name=node.slash_name,
        command_revision=node.revision,
        client_request_id=client_request_id,
        command_snapshot_encrypted=encrypt(snapshot.model_dump_json()),
    )
    session.add(request)
    await session.commit()
    logger.info(
        "library_command_enqueued",
        task_id=str(task.id),
        node_id=str(node.id),
        request_id=str(request.id),
        revision=node.revision,
    )
    return request


async def snapshot_command(
    session: AsyncSession,
    *,
    node: Node,
    invocation: str,
    arguments: CommandArguments,
) -> CommandSnapshot:
    return CommandSnapshot(
        invocation=invocation,
        raw_arguments=arguments.raw,
        arguments=arguments.values,
        name=node.name,
        node_type=node.node_type,
        prompt_template=node.prompt_template,
        script_language=node.script_language,
        script_content=node.script_content,
        docker_image=await resolve_runner_image(session, node),
        timeout_seconds=node.timeout_seconds,
        max_retries=node.max_retries,
        retry_base_delay_seconds=node.retry_base_delay_seconds,
        llm_output_last_n=node.llm_output_last_n,
        reasoning_effort=node.reasoning_effort,
    )


def load_snapshot(request: TaskManualRequestQueue) -> CommandSnapshot:
    assert request.command_snapshot_encrypted is not None
    return CommandSnapshot.model_validate_json(decrypt(request.command_snapshot_encrypted))


async def render_command(
    session: AsyncSession,
    *,
    task: Task,
    request: TaskManualRequestQueue,
    snapshot: CommandSnapshot,
) -> RenderedText | None:
    if snapshot.node_type is NodeType.SCRIPT:
        return None
    arguments = CommandArguments(
        name=request.command_name or "",
        raw=snapshot.raw_arguments,
        values=snapshot.arguments,
    )
    prepared = prepare_arguments(snapshot.prompt_template or "", arguments)
    rendered = await render_for_task(
        session, task, prepared.text, last_n=snapshot.llm_output_last_n
    )
    return RenderedText(
        text=prepared.expand(rendered.text), display=prepared.expand(rendered.display)
    )


async def preview_command(session: AsyncSession, *, task: Task, invocation: str) -> str:
    node = await _find_command(session, owner_id=task.created_by, invocation=invocation)
    arguments = parse_invocation(invocation)
    snapshot = await snapshot_command(
        session, node=node, invocation=invocation, arguments=arguments
    )
    if node.node_type is NodeType.SCRIPT:
        serialized = json.dumps(arguments.values, ensure_ascii=False)
        return f"Аргументы: {serialized}\n\n{node.script_content}"
    request = TaskManualRequestQueue(command_name=node.slash_name)
    prompt = await render_command(session, task=task, request=request, snapshot=snapshot)
    assert prompt is not None
    return prompt.display
