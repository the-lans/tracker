"""
Проверки перед запуском задачи (раздел 12.2 ТЗ): кнопка «Запустить»,
«Перезапустить» и автозапуск по расписанию проходят одни и те же.

LLM-аккаунт у задачи необязателен (раздел 3.1, решение №19 плана): задача
может быть цепочкой скриптов. Но ноды, которым нужна сессия Claude Code, и
пересказ родительской задачи без аккаунта не запускаются — ошибка до старта,
а не сбой посреди пайплайна.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeType
from db.models.pipelines import Node, TaskNode
from services.errors import ValidationError
from services.template_context import ensure_no_repository_env_conflicts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

# Ноды, которые выполняются без сессии Claude Code.
NODE_TYPES_WITHOUT_LLM = frozenset({NodeType.SCRIPT, NodeType.CLEAR_CONTEXT})


def requires_llm_account(node: Node) -> bool:
    return node.node_type not in NODE_TYPES_WITHOUT_LLM


async def _enabled_llm_node_names(db_session: AsyncSession, task: Task) -> list[str]:
    stmt = (
        sa.select(Node.name)
        .join(TaskNode, TaskNode.node_id == Node.id)
        .where(
            TaskNode.task_id == task.id,
            TaskNode.is_enabled == True,  # noqa: E712 — sa.Boolean-колонка, не Python bool
            Node.node_type.not_in(NODE_TYPES_WITHOUT_LLM),
        )
        .order_by(TaskNode.order_index)
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def ensure_llm_account_for_launch(db_session: AsyncSession, task: Task) -> None:
    if task.llm_account_id is not None:
        return
    if task.use_parent_summary:
        raise ValidationError("Пересказ родительской задачи выполняет LLM — выберите LLM-аккаунт")
    llm_nodes = await _enabled_llm_node_names(db_session, task)
    if llm_nodes:
        raise ValidationError(
            "Для нод, которые выполняет LLM, нужен LLM-аккаунт: "
            f"{', '.join(llm_nodes)}. Выберите аккаунт или отключите эти ноды",
        )


async def ensure_task_launchable(db_session: AsyncSession, task: Task) -> None:
    await ensure_no_repository_env_conflicts(db_session, task_id=task.id)
    await ensure_llm_account_for_launch(db_session, task)
