"""
Владение записями (раздел 19.2 ТЗ, решение №16 плана реализации).

Задачи, пайплайны (с их нодами), промты библиотеки, шаблоны и LLM-аккаунты
(решение №17) — личные: `user` видит и меняет только записи со своим
`created_by`, `admin` — все. Чужая запись неотличима от несуществующей (404):
ответ не раскрывает, что она есть. Репозитории и переменные окружения —
общие и здесь не проверяются.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from db.models.enums import UserRole
from db.models.llm import LlmAccount
from db.models.pipelines import Node, Pipeline
from db.models.repositories import Template
from db.models.tasks import Task
from db.models.users import User
from services.errors import NotFoundError, UnauthorizedError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import InstrumentedAttribute

OwnedRecord = Task | Pipeline | Node | Template | LlmAccount
OwnedModel = type[Task] | type[Pipeline] | type[Node] | type[Template] | type[LlmAccount]


def is_admin(user: User) -> bool:
    return user.role is UserRole.ADMIN


def owner_filter(column: InstrumentedAttribute[uuid.UUID], user: User) -> sa.ColumnElement[bool]:
    """Условие выборки «только свои записи»; у `admin` ограничения нет."""
    if is_admin(user):
        return sa.true()
    return column == user.id


def can_access(record: OwnedRecord, user: User) -> bool:
    return is_admin(user) or record.created_by == user.id


async def _get_owned(
    db_session: AsyncSession,
    model: OwnedModel,
    record_id: uuid.UUID,
    *,
    user: User,
    label: str,
) -> Any:
    record: OwnedRecord | None = await db_session.get(model, record_id)
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


async def get_llm_account_for_user(
    db_session: AsyncSession,
    llm_account_id: uuid.UUID,
    *,
    user: User,
) -> LlmAccount:
    llm_account: LlmAccount = await _get_owned(
        db_session,
        LlmAccount,
        llm_account_id,
        user=user,
        label="LLM-аккаунт",
    )
    return llm_account


async def ensure_llm_account_of_owner(
    db_session: AsyncSession,
    llm_account_id: uuid.UUID,
    *,
    owner_id: uuid.UUID,
) -> None:
    """
    Раздел 19.2: LLM-аккаунт задачи — только один из аккаунтов её автора,
    в том числе когда задачу создаёт или меняет `admin`.
    """
    llm_account = await db_session.get(LlmAccount, llm_account_id)
    if llm_account is None or llm_account.created_by != owner_id:
        raise NotFoundError(f"LLM-аккаунт {llm_account_id} не найден у автора задачи")


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
