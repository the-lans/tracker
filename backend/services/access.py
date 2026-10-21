"""
Владение записями (раздел 19.2 ТЗ, решение №16 плана реализации).

Задачи, пайплайны (с их нодами), промты библиотеки и шаблоны — личные:
`user` видит и меняет только записи со своим `created_by`, `admin` — все.
Чужая запись неотличима от несуществующей (404): ответ не раскрывает, что
она есть. Репозитории, LLM-аккаунты и переменные окружения — общие и здесь
не проверяются.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from db.models.enums import UserRole
from db.models.pipelines import Node, Pipeline
from db.models.repositories import Template
from db.models.tasks import Task
from db.models.users import User
from services.errors import NotFoundError, UnauthorizedError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute

OwnedModel = type[Task] | type[Pipeline] | type[Node] | type[Template]


def is_admin(user: User) -> bool:
    return user.role is UserRole.ADMIN


def owner_filter(column: InstrumentedAttribute[uuid.UUID], user: User) -> sa.ColumnElement[bool]:
    """Условие выборки «только свои записи»; у `admin` ограничения нет."""
    if is_admin(user):
        return sa.true()
    return column == user.id


def can_access(record: Task | Pipeline | Node | Template, user: User) -> bool:
    return is_admin(user) or record.created_by == user.id


async def _get_owned(
    db_session: AsyncSession,
    model: OwnedModel,
    record_id: uuid.UUID,
    *,
    user: User,
    label: str,
) -> Any:
    record: Task | Pipeline | Node | Template | None = await db_session.get(model, record_id)
    if record is None or not can_access(record, user):
        raise NotFoundError(f"{label} {record_id} не найден(а)")
    return record


async def get_task_for_user(db_session: AsyncSession, task_id: uuid.UUID, *, user: User) -> Task:
    task: Task = await _get_owned(db_session, Task, task_id, user=user, label="Задача")
    return task


async def get_pipeline_for_user(
    db_session: AsyncSession,
    pipeline_id: uuid.UUID,
    *,
    user: User,
) -> Pipeline:
    pipeline: Pipeline = await _get_owned(
        db_session,
        Pipeline,
        pipeline_id,
        user=user,
        label="Пайплайн",
    )
    return pipeline


async def get_node_for_user(db_session: AsyncSession, node_id: uuid.UUID, *, user: User) -> Node:
    node: Node = await _get_owned(db_session, Node, node_id, user=user, label="Нода")
    return node


async def get_template_for_user(
    db_session: AsyncSession,
    template_id: uuid.UUID,
    *,
    user: User,
) -> Template:
    template: Template = await _get_owned(
        db_session,
        Template,
        template_id,
        user=user,
        label="Шаблон",
    )
    return template


async def authorize_task_stream(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
) -> User:
    """
    Раздел 19.2 для WebSocket-канала задачи: токен подписан, но доступ к
    каналу есть только у активного автора задачи или `admin`.

    ``UnauthorizedError`` — пользователь удалён или заблокирован;
    ``NotFoundError`` — задачи нет или она чужая.
    """
    user = await db_session.get(User, user_id)
    if user is None or not user.is_active:
        message = "Пользователь не найден или заблокирован"
        raise UnauthorizedError(message)
    await get_task_for_user(db_session, task_id, user=user)
    return user
