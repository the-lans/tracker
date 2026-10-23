"""
Правка полей задачи после создания (раздел 12.1, 14.2, 15.2 ТЗ).

``auto_accept_plan`` меняется в любой момент до `done`; остальные поля —
только пока задача в `new`. LLM-аккаунт — только один из аккаунтов автора
задачи, даже если правит `admin` (раздел 19.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from db.models.enums import TaskStatus
from services.access import ensure_llm_account_of_owner
from services.errors import ValidationError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

_ANYTIME_FIELD = "auto_accept_plan"


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
    if changes.get("llm_account_id") is not None:
        await ensure_llm_account_of_owner(
            db_session,
            changes["llm_account_id"],
            owner_id=task.created_by,
        )

    for field, value in changes.items():
        setattr(task, field, value)
    if auto_accept_plan is not None:
        task.auto_accept_plan = auto_accept_plan
    await db_session.commit()
    await db_session.refresh(task)
    return task
