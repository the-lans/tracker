"""
Правка полей задачи после создания (раздел 12.1, 14.2, 15.2 ТЗ).

``auto_accept_plan`` меняется в любой момент до `done`; остальные поля —
только пока задача в `new`. LLM-аккаунт — только один из аккаунтов автора
задачи, даже если правит `admin` (раздел 19.2). Сессия Claude Code хранится в
каталоге конфигурации своего LLM-аккаунта (раздел 19.5), поэтому смена
аккаунта у задачи, уже имевшей сессию (после «Вернуть в новые»), забывает
`tasks.session_id` — следующий запуск начнёт новую сессию.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app_logging.config import get_logger
from db.models.enums import TaskStatus
from services.access import ensure_llm_account_of_owner
from services.errors import ValidationError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

logger = get_logger("task_editing")

_ANYTIME_FIELD = "auto_accept_plan"
_LLM_ACCOUNT_FIELD = "llm_account_id"


def _forget_session_of_other_account(task: Task, changes: dict[str, Any]) -> None:
    if _LLM_ACCOUNT_FIELD not in changes or task.session_id is None:
        return
    if changes[_LLM_ACCOUNT_FIELD] == task.llm_account_id:
        return
    logger.info(
        "task_session_forgotten_on_account_change",
        task_id=str(task.id),
        previous_session_id=task.session_id,
    )
    task.session_id = None


async def update_task(
    db_session: AsyncSession,
    *,
    task: Task,
    changes: dict[str, Any],
) -> Task:
    changes = dict(changes)
    auto_accept_plan = changes.pop(_ANYTIME_FIELD, None)
    if changes and task.status is not TaskStatus.NEW:
        raise ValidationError("Поля задачи можно менять только в статусе new")
    if auto_accept_plan is not None and task.status is TaskStatus.DONE:
        raise ValidationError("Задача уже завершена")
    if changes.get(_LLM_ACCOUNT_FIELD) is not None:
        await ensure_llm_account_of_owner(
            db_session,
            changes[_LLM_ACCOUNT_FIELD],
            owner_id=task.created_by,
        )
    _forget_session_of_other_account(task, changes)

    for field, value in changes.items():
        setattr(task, field, value)
    if auto_accept_plan is not None:
        task.auto_accept_plan = auto_accept_plan
    await db_session.commit()
    await db_session.refresh(task)
    return task
