"""
Правка полей задачи после создания (раздел 12.1, 14.2, 15.2 ТЗ).

``auto_accept_plan`` меняется в любой момент до `done`; остальные поля —
только пока задача в `new`. LLM-аккаунт — только один из аккаунтов автора
задачи, даже если правит `admin` (раздел 19.2). Сессия хранится в каталоге
задачи, а не аккаунта (раздел 6.4), поэтому смена стартового аккаунта у задачи,
уже имевшей сессию (после «Вернуть в новые»), сессию не забывает: следующий
запуск продолжит её на выбранном аккаунте (раздел 14.1, 19.7).
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


def _restart_on_chosen_account(task: Task, changes: dict[str, Any]) -> None:
    """Новый стартовый аккаунт — первое обращение запуска уйдёт ему (п. 1 раздела 19.7)."""
    if _LLM_ACCOUNT_FIELD not in changes or changes[_LLM_ACCOUNT_FIELD] == task.llm_account_id:
        return
    task.current_llm_account_id = None
    logger.info("task_start_llm_account_changed", task_id=str(task.id))


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
    _restart_on_chosen_account(task, changes)

    for field, value in changes.items():
        setattr(task, field, value)
    if auto_accept_plan is not None:
        task.auto_accept_plan = auto_accept_plan
    await db_session.commit()
    await db_session.refresh(task)
    return task
