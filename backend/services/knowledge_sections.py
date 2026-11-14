"""
Серверное управление разделами базы знаний и проверка доступа.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import UserRole
from db.models.knowledge import KnowledgeSection
from db.models.users import User
from db.queries import knowledge as queries
from services.errors import ForbiddenError, NotFoundError
from services.knowledge_access import KnowledgeAccess, knowledge_access_for_role
from services.knowledge_objects import KnowledgeSectionSnapshot as KnowledgeSectionSnapshot

MAX_SECTION_NAME_LENGTH = 255
SESSION_KNOWLEDGE_ACCESS: ContextVar[dict[uuid.UUID, KnowledgeAccess] | None] = ContextVar(
    "session_knowledge_access",
    default=None,
)


async def list_sections(db: AsyncSession, *, user: User) -> list[KnowledgeSection]:
    return await queries.sections(db, readable_only=user.role is not UserRole.ADMIN)


async def require_section(
    db: AsyncSession,
    *,
    section_id: uuid.UUID,
    user: User,
    write: bool = False,
) -> KnowledgeSection:
    section = await queries.section(db, section_id)
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


async def section_snapshot(db: AsyncSession, *, user: User) -> list[KnowledgeSectionSnapshot]:
    return [
        KnowledgeSectionSnapshot(
            id=s.id, name=s.name, user_read=s.user_read, user_write=s.user_write
        )
        for s in await list_sections(db, user=user)
    ]
