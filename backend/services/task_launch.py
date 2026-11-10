"""
Проверки перед запуском задачи (раздел 12.2 ТЗ): кнопка «Запустить»,
«Перезапустить» и автозапуск по расписанию проходят одни и те же.

Стартовый LLM-аккаунт у задачи необязателен (раздел 3.1): пустой — аккаунт
выбирается автоматически (раздел 19.7), а задаче из одних скриптов LLM не
нужен вовсе. Но ноды, которым нужна сессия Claude Code, пересказ родительской
задачи и чат «Уточняется» без доступного аккаунта автора не запускаются —
ошибка до старта, а не сбой посреди пайплайна.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import LlmAccountStatus, NodeType, TaskStatus
from db.models.llm import LlmAccount
from db.models.pipelines import Node, TaskNode
from services.errors import ValidationError
from services.llm_providers import PROVIDERS
from services.maintenance import ensure_not_in_maintenance
from services.template_context import ensure_no_repository_env_conflicts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

# Ноды, которые выполняются без сессии Claude Code.
NODE_TYPES_WITHOUT_LLM = frozenset({NodeType.SCRIPT, NodeType.CLEAR_CONTEXT})
# Раздел 13.1: без пайплайна выполнять нечего — иначе задача «выполнилась» бы
# пустой: пуш ветки без изменений и уведомление «Задача выполнена».
PIPELINE_REQUIRED_MESSAGE = "Сначала выберите пайплайн задачи"
LLM_ACCOUNT_UNAVAILABLE = (
    "Нет доступного LLM-аккаунта: войдите в аккаунт на странице «LLM-аккаунты»"
)
SESSION_WITHOUT_LLM = (
    "Задача работает без LLM: промт выполняет LLM — выберите стартовый LLM-аккаунт до запуска"
)
# Аккаунт может работать: выбор хода его не исключает (раздел 19.7).
_USABLE_ACCOUNT_STATUSES = (LlmAccountStatus.ACTIVE, LlmAccountStatus.RATE_LIMITED)


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


async def task_needs_llm(db_session: AsyncSession, task: Task) -> bool:
    """Задаче нужна сессия Claude Code: включённые LLM-ноды или пересказ родителя."""
    return task.use_parent_summary or bool(await _enabled_llm_node_names(db_session, task))


async def author_has_llm_account(db_session: AsyncSession, user_id: uuid.UUID) -> bool:
    """У автора есть аккаунт, который может работать: вход, модель, известный провайдер."""
    stmt = sa.select(LlmAccount.id).where(
        LlmAccount.created_by == user_id,
        LlmAccount.status.in_(_USABLE_ACCOUNT_STATUSES),
        LlmAccount.default_model.is_not(None),
        LlmAccount.provider.in_(list(PROVIDERS)),
    )
    return await db_session.scalar(stmt.limit(1)) is not None


async def task_uses_llm(db_session: AsyncSession, task: Task) -> bool:
    """
    Сессия задачи — с Claude Code (раздел 3.1): выбран стартовый аккаунт,
    задаче нужен LLM или идёт чат «Уточняется»; иначе — без LLM.
    """
    if task.llm_account_id is not None or task.status is TaskStatus.REFINING:
        return True
    return await task_needs_llm(db_session, task)


async def ensure_llm_account_for_launch(db_session: AsyncSession, task: Task) -> None:
    if await author_has_llm_account(db_session, task.created_by):
        return
    if task.use_parent_summary:
        message = f"Пересказ родительской задачи выполняет LLM. {LLM_ACCOUNT_UNAVAILABLE}"
        raise ValidationError(message)
    llm_nodes = await _enabled_llm_node_names(db_session, task)
    if llm_nodes:
        raise ValidationError(
            f"Ноды выполняет LLM: {', '.join(llm_nodes)}. {LLM_ACCOUNT_UNAVAILABLE} "
            "или отключите эти ноды",
        )


async def ensure_llm_for_request(
    db_session: AsyncSession,
    task: Task,
    *,
    needs_llm: bool,
) -> None:
    """
    Ручной запрос (разделы 8, 14.4): промту LLM нужна сессия с Claude Code и
    доступный аккаунт автора; чату «Уточняется» — аккаунт для любого запроса.
    """
    if not needs_llm and task.status is not TaskStatus.REFINING:
        return
    if not await task_uses_llm(db_session, task):
        raise ValidationError(SESSION_WITHOUT_LLM)
    if not await author_has_llm_account(db_session, task.created_by):
        raise ValidationError(LLM_ACCOUNT_UNAVAILABLE)


async def ensure_task_launchable(db_session: AsyncSession, task: Task) -> None:
    await ensure_not_in_maintenance()
    if task.pipeline_id is None:
        raise ValidationError(PIPELINE_REQUIRED_MESSAGE)
    await ensure_no_repository_env_conflicts(db_session, task_id=task.id)
    await ensure_llm_account_for_launch(db_session, task)
