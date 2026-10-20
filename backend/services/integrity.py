"""Guard'ы целостности из раздела 3.2 ТЗ, не выражаемые чистым FK/constraint.

Удаление пайплайна/промта-библиотеки/репозитория, всё ещё используемого
задачей, запрещено на уровне API — вместо удаления предлагается архивация.
Эти функции не удаляют и не архивируют ничего сами — они только проверяют,
можно ли выполнить удаление, и поднимают `ConflictError`, если нет; вызывать
их обязан код эндпоинта удаления (раздел API — этап 12 плана реализации).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import TaskStatus
from db.models.prompts import TaskLibraryPrompt
from db.models.tasks import Task, TaskRepository
from services.errors import ConflictError

# Репозиторий очищается вручную только в этих двух статусах (CLAUDE.md,
# правило 5) — во всех остальных задача считается "активной" применительно
# к запрету удаления привязанного репозитория (раздел 3.2 ТЗ).
_TERMINAL_TASK_STATUSES = (TaskStatus.DONE, TaskStatus.FAILED)


async def ensure_pipeline_deletable(session: AsyncSession, pipeline_id: uuid.UUID) -> None:
    """Запрещает удаление пайплайна, используемого хотя бы одной задачей."""
    stmt = sa.select(Task.id).where(Task.pipeline_id == pipeline_id).limit(1)
    if (await session.execute(stmt)).first() is not None:
        raise ConflictError(
            "Пайплайн используется хотя бы одной задачей — вместо удаления доступна архивация",
        )


async def ensure_node_deletable(session: AsyncSession, node_id: uuid.UUID) -> None:
    """Запрещает удаление системного промта, привязанного хотя бы к одной задаче."""
    stmt = (
        sa.select(TaskLibraryPrompt.id)
        .where(TaskLibraryPrompt.node_id == node_id)
        .limit(1)
    )
    if (await session.execute(stmt)).first() is not None:
        raise ConflictError(
            "Системный промт привязан хотя бы к одной задаче — вместо удаления доступна архивация",
        )


async def ensure_repository_deletable(session: AsyncSession, repository_id: uuid.UUID) -> None:
    """Запрещает удаление репозитория, привязанного к активной (не терминальной) задаче."""
    stmt = (
        sa.select(TaskRepository.id)
        .join(Task, Task.id == TaskRepository.task_id)
        .where(
            TaskRepository.repository_id == repository_id,
            Task.status.not_in(_TERMINAL_TASK_STATUSES),
        )
        .limit(1)
    )
    if (await session.execute(stmt)).first() is not None:
        raise ConflictError("Репозиторий привязан к активной задаче")


async def count_library_prompt_usage(db_session: AsyncSession) -> list[tuple[uuid.UUID, int]]:
    """Раздел 15.5: число задач, к которым привязан каждый промт библиотеки."""
    stmt = (
        sa.select(TaskLibraryPrompt.node_id, sa.func.count(sa.distinct(TaskLibraryPrompt.task_id)))
        .group_by(TaskLibraryPrompt.node_id)
    )
    return [(node_id, int(count)) for node_id, count in (await db_session.execute(stmt)).all()]
