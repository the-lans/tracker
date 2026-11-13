"""
Категории задач (раздел 15.7 ТЗ).

Категория — личная: пользователь видит и выбирает только свои, `admin` тоже
(у каждого пользователя свои категории). Её настройки — пайплайн, «Принять
план автоматически», системные промты, приоритет в очереди и «Занимать
слот» — копируются в новую задачу категории; пайплайн — и в задачу до
запуска без пайплайна, которой категорию выбрали позже. Дальше задача
живёт со своими значениями: правка категории задачи не меняет.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.categories import TaskCategory, TaskCategoryLibraryPrompt
from db.models.pipelines import Node, Pipeline
from db.models.prompts import TaskLibraryPrompt
from db.models.tasks import DEFAULT_QUEUE_PRIORITY
from services.access import get_node_for_user, get_pipeline_for_user
from services.errors import ConflictError, NotFoundError, ValidationError
from services.integrity import ensure_library_prompt_attachable, ensure_pipeline_attachable
from services.task_nodes import replace_pipeline_snapshot
from services.task_status import PRE_LAUNCH_STATUSES, lock_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task
    from db.models.users import User

logger = get_logger("task_categories")

CATEGORY_NAME_TAKEN = "Категория с таким названием уже есть"


@dataclass(frozen=True, slots=True)
class CategoryDraft:
    name: str
    pipeline_id: uuid.UUID | None = None
    auto_accept_plan: bool = False
    queue_priority: int = DEFAULT_QUEUE_PRIORITY
    occupies_slot: bool = False
    library_prompt_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CategoryView:
    category: TaskCategory
    library_prompt_ids: list[uuid.UUID]


def _normalized_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValidationError("Укажите название категории")
    return normalized


async def get_category_of_owner(
    db_session: AsyncSession,
    category_id: uuid.UUID,
    *,
    owner_id: uuid.UUID,
) -> TaskCategory:
    """Чужая категория неотличима от несуществующей (раздел 19.2)."""
    category = await db_session.get(TaskCategory, category_id)
    if category is None or category.created_by != owner_id:
        raise NotFoundError(f"Категория {category_id} не найдена")
    return category


async def _prompt_ids_by_category(
    db_session: AsyncSession,
    category_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    stmt = (
        sa.select(TaskCategoryLibraryPrompt.category_id, TaskCategoryLibraryPrompt.node_id)
        .join(Node, Node.id == TaskCategoryLibraryPrompt.node_id)
        .where(TaskCategoryLibraryPrompt.category_id.in_(category_ids))
        .order_by(Node.name)
    )
    result: dict[uuid.UUID, list[uuid.UUID]] = {category_id: [] for category_id in category_ids}
    for category_id, node_id in (await db_session.execute(stmt)).all():
        result[category_id].append(node_id)
    return result


async def list_categories(db_session: AsyncSession, *, owner_id: uuid.UUID) -> list[CategoryView]:
    stmt = (
        sa.select(TaskCategory)
        .where(TaskCategory.created_by == owner_id)
        .order_by(TaskCategory.name)
    )
    categories = list((await db_session.execute(stmt)).scalars().all())
    prompt_ids = await _prompt_ids_by_category(db_session, [item.id for item in categories])
    return [CategoryView(category, prompt_ids[category.id]) for category in categories]


async def category_view(db_session: AsyncSession, category: TaskCategory) -> CategoryView:
    prompt_ids = await _prompt_ids_by_category(db_session, [category.id])
    return CategoryView(category, prompt_ids[category.id])


async def _pipeline_has_nodes(db_session: AsyncSession, pipeline_id: uuid.UUID) -> bool:
    stmt = sa.select(sa.exists().where(Node.pipeline_id == pipeline_id))
    return bool(await db_session.scalar(stmt))


async def _ensure_pipeline_choosable(
    db_session: AsyncSession,
    pipeline_id: uuid.UUID,
    *,
    user: User,
) -> None:
    """
    Пайплайн без нод задаче категории не привязать — его не выбрать и в категории.
    """
    pipeline = await get_pipeline_for_user(db_session, pipeline_id, user=user)
    ensure_pipeline_attachable(pipeline)
    if not await _pipeline_has_nodes(db_session, pipeline_id):
        raise ValidationError(
            f"В пайплайне «{pipeline.name}» нет нод — добавьте их или выберите другой пайплайн",
        )


async def _ensure_prompts_choosable(
    db_session: AsyncSession,
    node_ids: set[uuid.UUID],
    *,
    user: User,
) -> None:
    for node_id in node_ids:
        node = await get_node_for_user(db_session, node_id, user=user)
        ensure_library_prompt_attachable(node)


async def _replace_prompt_links(
    db_session: AsyncSession,
    *,
    category_id: uuid.UUID,
    node_ids: list[uuid.UUID],
) -> None:
    await db_session.execute(
        sa.delete(TaskCategoryLibraryPrompt).where(
            TaskCategoryLibraryPrompt.category_id == category_id,
        ),
    )
    for node_id in dict.fromkeys(node_ids):
        db_session.add(TaskCategoryLibraryPrompt(category_id=category_id, node_id=node_id))


async def _ensure_name_free(
    db_session: AsyncSession,
    *,
    name: str,
    owner_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
) -> None:
    stmt = sa.select(TaskCategory.id).where(
        TaskCategory.created_by == owner_id,
        TaskCategory.name == name,
    )
    if category_id is not None:
        stmt = stmt.where(TaskCategory.id != category_id)
    if await db_session.scalar(stmt.limit(1)) is not None:
        raise ConflictError(CATEGORY_NAME_TAKEN)


async def _commit_unique_name(db_session: AsyncSession) -> None:
    """Одновременное сохранение с тем же названием — тот же 409, а не 500."""
    try:
        await db_session.commit()
    except sa.exc.IntegrityError as exc:
        await db_session.rollback()
        raise ConflictError(CATEGORY_NAME_TAKEN) from exc


async def create_category(
    db_session: AsyncSession,
    *,
    draft: CategoryDraft,
    user: User,
) -> CategoryView:
    if draft.pipeline_id is not None:
        await _ensure_pipeline_choosable(db_session, draft.pipeline_id, user=user)
    await _ensure_prompts_choosable(db_session, set(draft.library_prompt_ids), user=user)
    name = _normalized_name(draft.name)
    await _ensure_name_free(db_session, name=name, owner_id=user.id)
    category = TaskCategory(
        id=uuid.uuid4(),
        name=name,
        pipeline_id=draft.pipeline_id,
        auto_accept_plan=draft.auto_accept_plan,
        queue_priority=draft.queue_priority,
        occupies_slot=draft.occupies_slot,
        created_by=user.id,
    )
    db_session.add(category)
    await _replace_prompt_links(
        db_session,
        category_id=category.id,
        node_ids=draft.library_prompt_ids,
    )
    await _commit_unique_name(db_session)
    await db_session.refresh(category)
    logger.info("task_category_created", category_id=str(category.id))
    return await category_view(db_session, category)


async def update_category(
    db_session: AsyncSession,
    *,
    category: TaskCategory,
    draft: CategoryDraft,
    user: User,
) -> CategoryView:
    """
    Уже выбранные пайплайн и промты остаются, даже если их потом
    архивировали; новые — только из неархивных.
    """
    if draft.pipeline_id is not None and draft.pipeline_id != category.pipeline_id:
        await _ensure_pipeline_choosable(db_session, draft.pipeline_id, user=user)
    current_prompt_ids = (await category_view(db_session, category)).library_prompt_ids
    await _ensure_prompts_choosable(
        db_session,
        set(draft.library_prompt_ids) - set(current_prompt_ids),
        user=user,
    )
    name = _normalized_name(draft.name)
    await _ensure_name_free(
        db_session,
        name=name,
        owner_id=category.created_by,
        category_id=category.id,
    )
    category.name = name
    category.pipeline_id = draft.pipeline_id
    category.auto_accept_plan = draft.auto_accept_plan
    category.queue_priority = draft.queue_priority
    category.occupies_slot = draft.occupies_slot
    await _replace_prompt_links(
        db_session,
        category_id=category.id,
        node_ids=draft.library_prompt_ids,
    )
    await _commit_unique_name(db_session)
    await db_session.refresh(category)
    return await category_view(db_session, category)


async def delete_category(db_session: AsyncSession, category: TaskCategory) -> None:
    """Задачи категории остаются без категории (`ON DELETE SET NULL`)."""
    await db_session.delete(category)
    await db_session.commit()
    logger.info("task_category_deleted", category_id=str(category.id))


async def ensure_category_pipeline_usable(
    db_session: AsyncSession,
    category: TaskCategory,
) -> None:
    """
    Раздел 3.2: архивный пайплайн категории новой задаче не достаётся — 409;
    пайплайн, из которого после выбора в категории удалили все ноды, — 422.
    """
    if category.pipeline_id is None:
        return
    pipeline = await db_session.get(Pipeline, category.pipeline_id)
    if pipeline is None:
        return
    if pipeline.is_archived:
        raise ConflictError(
            f"Пайплайн категории «{pipeline.name}» в архиве — разархивируйте его "
            "или выберите в категории другой",
        )
    if not await _pipeline_has_nodes(db_session, pipeline.id):
        raise ValidationError(
            f"В пайплайне категории «{pipeline.name}» нет нод — добавьте их "
            "или выберите в категории другой пайплайн",
        )


async def _copy_pipeline(db_session: AsyncSession, *, task: Task, category: TaskCategory) -> None:
    if category.pipeline_id is None:
        return
    await ensure_category_pipeline_usable(db_session, category)
    await replace_pipeline_snapshot(db_session, task=task, pipeline_id=category.pipeline_id)


async def _copy_library_prompts(
    db_session: AsyncSession,
    *,
    task: Task,
    category_id: uuid.UUID,
) -> None:
    """
    Архивный промт новой задаче не выдаётся (раздел 3.2) — он пропускается.
    """
    stmt = (
        sa.select(TaskCategoryLibraryPrompt.node_id)
        .join(Node, Node.id == TaskCategoryLibraryPrompt.node_id)
        .where(
            TaskCategoryLibraryPrompt.category_id == category_id,
            Node.is_archived == False,  # noqa: E712
        )
        .order_by(Node.name)
    )
    now = datetime.now(UTC)
    for node_id in (await db_session.execute(stmt)).scalars().all():
        db_session.add(
            TaskLibraryPrompt(
                task_id=task.id,
                node_id=node_id,
                added_by=task.created_by,
                added_at=now,
            ),
        )


async def apply_category_to_new_task(
    db_session: AsyncSession,
    *,
    task: Task,
    category: TaskCategory,
) -> None:
    """
    Настройки категории — в только что созданную задачу, без коммита.
    Пайплайн категории проверяется до вставки задачи
    (`ensure_category_pipeline_usable`).
    """
    task.category_id = category.id
    task.auto_accept_plan = category.auto_accept_plan
    task.queue_priority = category.queue_priority
    task.occupies_slot = category.occupies_slot
    await _copy_library_prompts(db_session, task=task, category_id=category.id)
    await _copy_pipeline(db_session, task=task, category=category)
    await db_session.flush()


async def assign_task_category(
    db_session: AsyncSession,
    *,
    task: Task,
    category_id: uuid.UUID | None,
) -> None:
    """
    Смена категории задачи без коммита. Категория — только одна из категорий
    автора задачи, даже если правит `admin`. Задаче до запуска без пайплайна
    достаётся пайплайн категории; остальные настройки у задачи уже свои.
    """
    if category_id is None:
        task.category_id = None
        return
    category = await get_category_of_owner(db_session, category_id, owner_id=task.created_by)
    if category.pipeline_id is not None and task.pipeline_id is None:
        # Строка задачи — под блокировкой до коммита, как при выборе пайплайна.
        locked = await lock_task(db_session, task.id)
        if (
            locked is not None
            and locked.status in PRE_LAUNCH_STATUSES
            and locked.pipeline_id is None
        ):
            await _copy_pipeline(db_session, task=task, category=category)
    task.category_id = category.id
