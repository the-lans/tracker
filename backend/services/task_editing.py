"""
Правка полей задачи после создания (раздел 12.1, 14.2, 15.2 ТЗ).

``auto_accept_plan`` меняется в любой момент до `done`, приоритет в очереди,
галочка «Занимать слот» (управление прогоном, раздел 14.4) и категория
(раздел 15.7) — в любом статусе; остальные поля — только пока задача в
статусе до запуска.
LLM-аккаунт — только один из аккаунтов автора задачи, даже если правит
`admin` (раздел 19.2). Сессия хранится в каталоге
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
from services.task_categories import assign_task_category
from services.task_status import PRE_LAUNCH_STATUSES

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

logger = get_logger("task_editing")

_ANYTIME_FIELD = "auto_accept_plan"
_RUN_CONTROL_FIELDS = frozenset({"queue_priority", "occupies_slot"})
_LLM_ACCOUNT_FIELD = "llm_account_id"
_CATEGORY_FIELD = "category_id"


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
    if _CATEGORY_FIELD in changes:
        # Раздел 15.7: категория — разметка задачи, меняется в любом статусе.
        # Первой: блокировка строки задачи перечитывает её поля.
        await assign_task_category(
            db_session,
            task=task,
            category_id=changes.pop(_CATEGORY_FIELD),
        )
    auto_accept_plan = changes.pop(_ANYTIME_FIELD, None)
    # Пустое значение у этих полей ничего не меняет: в БД они NOT NULL.
    run_control = {
        field: value
        for field in _RUN_CONTROL_FIELDS & changes.keys()
        if (value := changes.pop(field)) is not None
    }
    if changes and task.status not in PRE_LAUNCH_STATUSES:
        raise ValidationError("Поля задачи можно менять только до запуска")
    if auto_accept_plan is not None and task.status is TaskStatus.DONE:
        raise ValidationError("Задача уже завершена")
    if changes.get(_LLM_ACCOUNT_FIELD) is not None:
        await ensure_llm_account_of_owner(
            db_session,
            changes[_LLM_ACCOUNT_FIELD],
            owner_id=task.created_by,
            # Прежний аккаунт можно оставить, даже если он уже выключен.
            require_active=changes[_LLM_ACCOUNT_FIELD] != task.llm_account_id,
        )
    _restart_on_chosen_account(task, changes)

    for field, value in {**changes, **run_control}.items():
        setattr(task, field, value)
    if auto_accept_plan is not None:
        task.auto_accept_plan = auto_accept_plan
    await db_session.commit()
    await db_session.refresh(task)
    return task
