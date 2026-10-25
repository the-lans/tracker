"""Состав включённых нод конкретной задачи (раздел 13.1, 13.2 ТЗ).

`task_nodes` — снимок нод пайплайна на момент привязки; отключение ноды
здесь не меняет сам пайплайн-шаблон и не создаёт записи в `node_logs`
(раздел 22). В снимок вставляются и свои ноды задачи (`nodes.task_id`) —
промты, нужные только ей.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import NodeType, TaskStatus
from db.models.logs import NodeLog
from db.models.pipelines import Node, TaskNode
from db.models.tasks import Task
from services.access import get_task_record_or_404
from services.errors import ConflictError, ValidationError
from services.integrity import commit_or_conflict, node_has_history
from services.pipeline_validation import (
    task_composition,
    validate_custom_node_templates,
    validate_node_shape,
)
from services.system_settings import resolve_node_execution_defaults
from services.task_status import lock_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("task_nodes")


@dataclass(frozen=True, slots=True)
class TaskNodeView:
    id: uuid.UUID
    node_id: uuid.UUID
    order_index: int
    is_enabled: bool
    pause_after: bool
    name: str
    node_type: NodeType
    editable: bool
    is_custom: bool
    # Текст — только у своей ноды задачи: её правят со страницы задачи.
    prompt_template: str | None
    command_invocation: str | None


@dataclass(frozen=True, slots=True)
class CustomNodeDraft:
    """Содержимое своей ноды задачи (раздел 13.1)."""

    name: str
    node_type: NodeType
    prompt_template: str | None = None
    command_invocation: str | None = None


def is_position_editable(task: Task, order_index: int) -> bool:
    """Правило 11 CLAUDE.md: в `new` — любая позиция; в `failed` — только
    ещё не начинавшие выполнение (`order_index > last_failed_order_index`);
    после запуска в остальных статусах — никакая."""
    if task.status is TaskStatus.NEW:
        return True
    if task.status is TaskStatus.FAILED and task.last_failed_order_index is not None:
        return order_index > task.last_failed_order_index
    return False


def is_task_node_editable(task: Task, task_node: TaskNode) -> bool:
    return is_position_editable(task, task_node.order_index)


def _locked_composition_message(task: Task) -> str:
    if task.status is TaskStatus.FAILED:
        return "Нода уже выполнялась в этом прогоне — менять её нельзя (раздел 13.2)"
    return "Состав нод можно менять только до запуска или после сбоя (раздел 13.2)"


async def load_task_node_rows(
    db_session: AsyncSession,
    task_id: uuid.UUID,
) -> list[tuple[TaskNode, Node]]:
    """
    Снимок нод задачи (`task_nodes`) вместе с нодами, в порядке выполнения.
    """
    stmt = (
        sa.select(TaskNode, Node)
        .join(Node, Node.id == TaskNode.node_id)
        .where(TaskNode.task_id == task_id)
        .order_by(TaskNode.order_index)
    )
    return [(task_node, node) for task_node, node in (await db_session.execute(stmt)).all()]


async def list_task_nodes(db_session: AsyncSession, task: Task) -> list[TaskNodeView]:
    return [
        TaskNodeView(
            id=task_node.id,
            node_id=node.id,
            order_index=task_node.order_index,
            is_enabled=task_node.is_enabled,
            pause_after=task_node.pause_after,
            name=node.name,
            node_type=node.node_type,
            editable=is_task_node_editable(task, task_node),
            is_custom=node.task_id is not None,
            prompt_template=node.prompt_template if node.task_id is not None else None,
            command_invocation=node.command_invocation if node.task_id is not None else None,
        )
        for task_node, node in await load_task_node_rows(db_session, task.id)
    ]


async def _get_task_node_or_404(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
) -> TaskNode:
    return await get_task_record_or_404(
        db_session,
        TaskNode,
        task_node_id,
        task_id=task.id,
        not_found=f"Нода {task_node_id} не найдена у этой задачи",
    )


async def set_task_node_enabled(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
    is_enabled: bool,
) -> TaskNode:
    task_node = await _get_task_node_or_404(db_session, task=task, task_node_id=task_node_id)
    if not is_task_node_editable(task, task_node):
        raise ConflictError(_locked_composition_message(task))
    task_node.is_enabled = is_enabled
    await db_session.commit()
    logger.info(
        "task_node_toggled",
        task_id=str(task.id),
        task_node_id=str(task_node_id),
        is_enabled=is_enabled,
    )
    return task_node


async def set_task_node_pause_after(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
    pause_after: bool,
) -> TaskNode:
    """
    Раздел 13.1, 13.2: отметка «пауза после» — управление прогоном, а не
    состав нод, поэтому меняется в любом статусе; оркестратор перечитывает
    её по завершении ноды.
    """
    task_node = await _get_task_node_or_404(db_session, task=task, task_node_id=task_node_id)
    task_node.pause_after = pause_after
    await db_session.commit()
    logger.info(
        "task_node_pause_toggled",
        task_id=str(task.id),
        task_node_id=str(task_node_id),
        pause_after=pause_after,
    )
    return task_node


async def bind_pipeline_to_task(
    db_session: AsyncSession,
    *,
    task: Task,
    pipeline_id: uuid.UUID,
    disabled_node_ids: set[uuid.UUID] | None,
) -> None:
    """
    Раздел 3.1, 13.1, правило 10 CLAUDE.md: снимок нод и `tasks.pipeline_id`
    — одной транзакцией.

    Пока задача в `new`, пайплайн можно сменить: прежний снимок заменяется
    новым в той же транзакции. Строка задачи блокируется до коммита, поэтому
    две одновременные привязки не складывают снимки (решение №19 плана).

    ``disabled_node_ids`` — чекбоксы, снятые пользователем при выборе
    пайплайна; `None` — выбор не делался, и выключены ноды с `is_skipped`
    (раздел 15.4, «пропуск по умолчанию»).
    """
    locked = await lock_task(db_session, task.id)
    if locked is None or locked.status is not TaskStatus.NEW:
        raise ValidationError(
            "Пайплайн можно выбрать или сменить только у задачи в статусе new — "
            "запущенную задачу сначала верните в новые",
        )
    nodes_stmt = sa.select(Node).where(Node.pipeline_id == pipeline_id).order_by(Node.order_index)
    nodes = list((await db_session.execute(nodes_stmt)).scalars().all())
    if not nodes:
        raise ValidationError("У пайплайна нет нод либо он не существует")
    if disabled_node_ids is None:
        disabled_node_ids = {node.id for node in nodes if node.is_skipped}
    unknown = disabled_node_ids - {node.id for node in nodes}
    if unknown:
        raise ValidationError("Отключаемые ноды не принадлежат выбранному пайплайну")

    await db_session.execute(sa.delete(TaskNode).where(TaskNode.task_id == task.id))
    await _delete_unused_custom_nodes(db_session, task.id)
    task.pipeline_id = pipeline_id
    for node in nodes:
        db_session.add(
            TaskNode(
                task_id=task.id,
                node_id=node.id,
                order_index=node.order_index or 0,
                is_enabled=node.id not in disabled_node_ids,
            ),
        )
    await db_session.commit()
    logger.info(
        "pipeline_bound_to_task",
        task_id=str(task.id),
        pipeline_id=str(pipeline_id),
        disabled_count=len(disabled_node_ids),
    )


async def _delete_unused_custom_nodes(db_session: AsyncSession, task_id: uuid.UUID) -> None:
    """
    Раздел 13.1: смена пайплайна заменяет снимок вместе со своими нодами;
    ноды с историей `node_logs` остаются как её часть.
    """
    has_history = sa.exists().where(NodeLog.node_id == Node.id)
    await db_session.execute(sa.delete(Node).where(Node.task_id == task_id, ~has_history))


def _apply_draft(node: Node, draft: CustomNodeDraft) -> None:
    """
    Текст хранится в поле своего типа: у слэш-команды — `command_invocation`
    (передаётся буквально, правило 2), у промта — `prompt_template`.
    """
    is_command = draft.node_type is NodeType.SLASH_COMMAND
    text = draft.command_invocation if is_command else draft.prompt_template
    if not draft.name.strip():
        raise ValidationError("Укажите название своего промта")
    if not (text or "").strip():
        raise ValidationError("Текст своего промта не может быть пустым")
    node.name = draft.name.strip()
    node.node_type = draft.node_type
    node.prompt_template = None if is_command else text
    node.command_invocation = text if is_command else None
    validate_node_shape(node)


async def _insert_position(
    db_session: AsyncSession,
    *,
    task: Task,
    after_task_node_id: uuid.UUID | None,
) -> int:
    """`order_index` новой ноды: сразу после выбранной или в начале снимка."""
    if after_task_node_id is not None:
        after = await _get_task_node_or_404(db_session, task=task, task_node_id=after_task_node_id)
        return after.order_index + 1
    first_stmt = sa.select(sa.func.min(TaskNode.order_index)).where(TaskNode.task_id == task.id)
    first = await db_session.scalar(first_stmt)
    return 0 if first is None else int(first)


async def add_custom_task_node(
    db_session: AsyncSession,
    *,
    task: Task,
    after_task_node_id: uuid.UUID | None,
    draft: CustomNodeDraft,
    pause_after: bool = False,
) -> TaskNode:
    """
    Раздел 13.1: свой промт вставляется в снимок задачи — последующие ноды
    сдвигаются, пайплайн-шаблон не меняется. Строка задачи блокируется, чтобы
    две одновременные вставки не получили одну позицию.
    """
    locked = await lock_task(db_session, task.id)
    if locked is None:
        raise ConflictError(_locked_composition_message(task))
    position = await _insert_position(
        db_session,
        task=locked,
        after_task_node_id=after_task_node_id,
    )
    if not is_position_editable(locked, position):
        raise ConflictError(_locked_composition_message(locked))

    defaults = await resolve_node_execution_defaults(
        db_session,
        timeout_seconds=None,
        max_retries=None,
        retry_base_delay_seconds=None,
    )
    node = Node(
        task_id=task.id,
        timeout_seconds=defaults.timeout_seconds,
        max_retries=defaults.max_retries,
        retry_base_delay_seconds=defaults.retry_base_delay_seconds,
        is_skipped=False,
        is_library_item=False,
        is_archived=False,
        created_by=task.created_by,
    )
    _apply_draft(node, draft)
    # Раздел 5.1: шаблоны проверяются по составу «как будет» — до записи.
    composition = await task_composition(db_session, task.id)
    shifted = [
        (index + 1 if index is not None and index >= position else index, other)
        for index, other in composition
    ]
    validate_custom_node_templates([*shifted, (position, node)])
    await db_session.execute(
        sa.update(TaskNode)
        .where(TaskNode.task_id == task.id, TaskNode.order_index >= position)
        .values(order_index=TaskNode.order_index + 1)
        .execution_options(synchronize_session="fetch"),
    )
    db_session.add(node)
    await db_session.flush()
    task_node = TaskNode(
        task_id=task.id,
        node_id=node.id,
        order_index=position,
        pause_after=pause_after,
    )
    db_session.add(task_node)
    await db_session.commit()
    logger.info(
        "custom_task_node_added",
        task_id=str(task.id),
        task_node_id=str(task_node.id),
        order_index=position,
    )
    return task_node


async def _get_editable_custom_node(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
) -> tuple[TaskNode, Node]:
    task_node = await _get_task_node_or_404(db_session, task=task, task_node_id=task_node_id)
    node = await db_session.get(Node, task_node.node_id)
    if node is None or node.task_id != task.id:
        raise ConflictError("Ноду пайплайна нельзя изменить или удалить — её можно отключить")
    if not is_task_node_editable(task, task_node):
        raise ConflictError(_locked_composition_message(task))
    return task_node, node


async def update_custom_task_node(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
    draft: CustomNodeDraft,
) -> TaskNode:
    """Раздел 13.1: правка своего промта — по правилам редактируемости состава."""
    task_node, node = await _get_editable_custom_node(
        db_session,
        task=task,
        task_node_id=task_node_id,
    )
    _apply_draft(node, draft)
    validate_custom_node_templates(await task_composition(db_session, task.id))
    await db_session.commit()
    logger.info("custom_task_node_updated", task_id=str(task.id), task_node_id=str(task_node_id))
    return task_node


async def delete_custom_task_node(
    db_session: AsyncSession,
    *,
    task: Task,
    task_node_id: uuid.UUID,
) -> None:
    """Раздел 3.2, 13.1: своя нода с историей не удаляется — её отключают."""
    task_node, node = await _get_editable_custom_node(
        db_session,
        task=task,
        task_node_id=task_node_id,
    )
    if await node_has_history(db_session, node.id):
        raise ConflictError("Свой промт уже выполнялся — удалить его нельзя, можно отключить")
    composition = await task_composition(db_session, task.id)
    validate_custom_node_templates([entry for entry in composition if entry[1].id != node.id])
    await db_session.delete(task_node)
    await db_session.flush()
    await db_session.delete(node)
    await commit_or_conflict(
        db_session,
        message="Свой промт уже выполнялся — удалить его нельзя, можно отключить",
    )
    logger.info("custom_task_node_deleted", task_id=str(task.id), task_node_id=str(task_node_id))
