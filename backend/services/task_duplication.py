"""
«Дублировать задачу» из `done` (раздел 14.2 ТЗ).

Копия получает новые код, поля и репозитории из формы создания, а от
исходной задачи — снимок пайплайна с отметками включённых нод, переменные
окружения задачи и системные промты. История, сессия, статусы, родитель и
автозапуск не переносятся: это новая задача, а не продолжение старой.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.env_vars import TaskEnvVariable
from db.models.pipelines import TaskNode
from db.models.prompts import TaskLibraryPrompt
from services.errors import ConflictError
from services.task_creation import add_task_with_repositories

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task
    from services.task_creation import TaskDraft

logger = get_logger("task_duplication")


async def _copy_task_nodes(db_session: AsyncSession, *, source: Task, target: Task) -> None:
    stmt = sa.select(TaskNode).where(TaskNode.task_id == source.id)
    for task_node in (await db_session.execute(stmt)).scalars().all():
        db_session.add(
            TaskNode(
                task_id=target.id,
                node_id=task_node.node_id,
                order_index=task_node.order_index,
                is_enabled=task_node.is_enabled,
            ),
        )


async def _copy_env_variables(db_session: AsyncSession, *, source: Task, target: Task) -> None:
    stmt = sa.select(TaskEnvVariable).where(TaskEnvVariable.task_id == source.id)
    for variable in (await db_session.execute(stmt)).scalars().all():
        # Значение копируется зашифрованным — расшифровка здесь не нужна.
        db_session.add(
            TaskEnvVariable(
                task_id=target.id,
                key=variable.key,
                value_encrypted=variable.value_encrypted,
            ),
        )


async def _copy_library_prompts(
    db_session: AsyncSession,
    *,
    source: Task,
    target: Task,
    added_by: uuid.UUID,
) -> None:
    stmt = sa.select(TaskLibraryPrompt).where(TaskLibraryPrompt.task_id == source.id)
    now = datetime.now(UTC)
    for prompt in (await db_session.execute(stmt)).scalars().all():
        db_session.add(
            TaskLibraryPrompt(
                task_id=target.id,
                node_id=prompt.node_id,
                added_by=added_by,
                added_at=now,
            ),
        )


async def duplicate_task(
    db_session: AsyncSession,
    *,
    source: Task,
    draft: TaskDraft,
    created_by: uuid.UUID,
) -> Task:
    """Новая задача и все копируемые данные — одной транзакцией (правило 10)."""
    if source.status is not TaskStatus.DONE:
        raise ConflictError("Дублировать можно только выполненную задачу")
    task = await add_task_with_repositories(db_session, draft=draft, created_by=created_by)
    task.pipeline_id = source.pipeline_id
    await _copy_task_nodes(db_session, source=source, target=task)
    await _copy_env_variables(db_session, source=source, target=task)
    await _copy_library_prompts(db_session, source=source, target=task, added_by=created_by)
    await db_session.commit()
    # `pipeline_id` проставлен отдельным UPDATE после вставки — `updated_at`,
    # вычисленный сервером, нужно перечитать до сериализации ответа.
    await db_session.refresh(task)
    logger.info("task_duplicated", source_task_id=str(source.id), task_id=str(task.id))
    return task
