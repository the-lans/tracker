"""Серверное управление разделами базы знаний и проверка доступа."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import UserRole
from db.models.knowledge import KnowledgeSection
from db.models.users import User
from services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from services.knowledge_access import KnowledgeAccess, knowledge_access_for_role

MAX_SECTION_NAME_LENGTH = 255
SESSION_KNOWLEDGE_ACCESS: ContextVar[dict[uuid.UUID, KnowledgeAccess] | None] = ContextVar(
    "session_knowledge_access",
    default=None,
)


async def list_sections(db: AsyncSession, *, user: User) -> list[KnowledgeSection]:
    query = sa.select(KnowledgeSection).order_by(KnowledgeSection.name)
    if user.role is not UserRole.ADMIN:
        query = query.where(KnowledgeSection.user_read.is_(True))
    return list(await db.scalars(query))


async def require_section(
    db: AsyncSession,
    *,
    section_id: uuid.UUID,
    user: User,
    write: bool = False,
) -> KnowledgeSection:
    section = await db.get(KnowledgeSection, section_id)
    if section is None:
        raise NotFoundError("Раздел базы знаний не найден")
    snapshot = SESSION_KNOWLEDGE_ACCESS.get()
    if snapshot is not None:
        access = snapshot.get(section_id, KnowledgeAccess(read=False, write=False))
    else:
        access = knowledge_access_for_role(
            user.role,
            user_access=KnowledgeAccess(read=section.user_read, write=section.user_write),
        )
    if not access.read:
        raise NotFoundError("Раздел базы знаний не найден")
    if write and not access.write:
        raise ForbiddenError("Раздел базы знаний доступен только для чтения")
    return section


async def create_section(
    db: AsyncSession,
    *,
    user: User,
    name: str,
    user_read: bool,
    user_write: bool,
) -> KnowledgeSection:
    if user.role is not UserRole.ADMIN:
        raise ForbiddenError("Создавать разделы может только администратор")
    name = name.strip()
    if not name or len(name) > MAX_SECTION_NAME_LENGTH:
        raise ValidationError("Укажите название раздела длиной до 255 символов")
    if user_write and not user_read:
        raise ValidationError("Право записи требует права чтения")
    section = KnowledgeSection(
        name=name,
        user_read=user_read,
        user_write=user_write,
        created_by=user.id,
    )
    db.add(section)
    try:
        await db.flush()
    except sa.exc.IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Раздел с таким названием уже существует") from exc
    return section


@dataclass(frozen=True, slots=True)
class KnowledgeSectionSnapshot:
    id: uuid.UUID
    name: str
    user_read: bool
    user_write: bool


async def section_snapshot(db: AsyncSession, *, user: User) -> list[KnowledgeSectionSnapshot]:
    return [
        KnowledgeSectionSnapshot(
            id=s.id, name=s.name, user_read=s.user_read, user_write=s.user_write
        )
        for s in await list_sections(db, user=user)
    ]
