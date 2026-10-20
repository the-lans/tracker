"""
Переменные окружения уровня задачи (раздел 3.1 `task_env_variables`, 5, 15.2 ТЗ).

Значение уровня задачи имеет приоритет над репозиторием и глобальным
(`services/template_context.py::resolve_env_value`). Хранится зашифрованным
и в обычных ответах не отдаётся (правило 8) — только через «Показать».
Подстановка идёт в момент отправки (раздел 5.1), поэтому менять переменные
можно и во время выполнения — запрещено лишь после `done`.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from db.models.env_vars import TaskEnvVariable
from services.crypto import decrypt, encrypt
from services.errors import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

logger = get_logger("task_env_variables")

# CLAUDE.md, раздел 5: `{{env.VAR_NAME}}` — сама переменная в UPPER_SNAKE_CASE.
ENV_KEY_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def _ensure_editable(task: Task) -> None:
    if task.status is TaskStatus.DONE:
        raise ConflictError("Переменные выполненной задачи менять нельзя")


async def _get_variable(
    db_session: AsyncSession,
    *,
    task: Task,
    variable_id: uuid.UUID,
) -> TaskEnvVariable:
    variable = await db_session.get(TaskEnvVariable, variable_id)
    if variable is None or variable.task_id != task.id:
        raise NotFoundError(f"Переменная {variable_id} не найдена у этой задачи")
    return variable


async def list_task_env_variables(db_session: AsyncSession, task: Task) -> list[TaskEnvVariable]:
    stmt = (
        sa.select(TaskEnvVariable)
        .where(TaskEnvVariable.task_id == task.id)
        .order_by(TaskEnvVariable.key)
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def create_task_env_variable(
    db_session: AsyncSession,
    *,
    task: Task,
    key: str,
    value: str,
) -> TaskEnvVariable:
    _ensure_editable(task)
    if not ENV_KEY_PATTERN.fullmatch(key):
        raise ValidationError("Ключ переменной — UPPER_SNAKE_CASE: латиница, цифры, «_»")
    taken = await db_session.scalar(
        sa.select(TaskEnvVariable.id).where(
            TaskEnvVariable.task_id == task.id,
            TaskEnvVariable.key == key,
        ),
    )
    if taken is not None:
        raise ConflictError(f"Переменная {key} у задачи уже есть")
    variable = TaskEnvVariable(task_id=task.id, key=key, value_encrypted=encrypt(value))
    db_session.add(variable)
    await db_session.commit()
    logger.info("task_env_variable_created", task_id=str(task.id), key=key)
    return variable


async def update_task_env_variable(
    db_session: AsyncSession,
    *,
    task: Task,
    variable_id: uuid.UUID,
    value: str,
) -> TaskEnvVariable:
    _ensure_editable(task)
    variable = await _get_variable(db_session, task=task, variable_id=variable_id)
    variable.value_encrypted = encrypt(value)
    await db_session.commit()
    logger.info("task_env_variable_updated", task_id=str(task.id), key=variable.key)
    return variable


async def delete_task_env_variable(
    db_session: AsyncSession,
    *,
    task: Task,
    variable_id: uuid.UUID,
) -> None:
    _ensure_editable(task)
    variable = await _get_variable(db_session, task=task, variable_id=variable_id)
    await db_session.delete(variable)
    await db_session.commit()
    logger.info("task_env_variable_deleted", task_id=str(task.id), key=variable.key)


async def reveal_task_env_variable(
    db_session: AsyncSession,
    *,
    task: Task,
    variable_id: uuid.UUID,
) -> str:
    variable = await _get_variable(db_session, task=task, variable_id=variable_id)
    return decrypt(variable.value_encrypted)
