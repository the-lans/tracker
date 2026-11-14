"""
Административные операции и обслуживание хранилища базы знаний.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app_logging.config import get_logger
from db.models.enums import UserRole
from db.models.knowledge import KnowledgeSection
from db.models.users import User
from db.queries import knowledge as queries
from services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from services.knowledge_sections import MAX_SECTION_NAME_LENGTH
from services.knowledge_storage import collect_objects
from services.knowledge_views import finish_changes

logger = get_logger("knowledge_admin")


def _require_admin(user: User) -> None:
    if user.role is not UserRole.ADMIN:
        raise ForbiddenError("Управление разделами доступно администратору")


def _section_name(name: str) -> str:
    name = name.strip()
    if not name or len(name) > MAX_SECTION_NAME_LENGTH:
        raise ValidationError(
            f"Укажите название раздела длиной до {MAX_SECTION_NAME_LENGTH} символов"
        )
    return name


async def create_section(
    *, db: AsyncSession, user: User, name: str, user_read: bool, user_write: bool
) -> KnowledgeSection:
    _require_admin(user)
    name = _section_name(name)
    if user_write and not user_read:
        raise ValidationError("Право записи требует права чтения")
    await queries.lock_storage(db)
    if await queries.section_name_taken(db, name=name):
        raise ConflictError("Раздел с таким названием уже существует")
    section = KnowledgeSection(
        name=name,
        user_read=user_read,
        user_write=user_write,
        created_by=user.id,
        publication_pending=True,
    )
    db.add(section)
    await db.flush()
    identifier = section.id
    await finish_changes(db, section_ids={identifier})
    await db.refresh(section)
    return section


async def edit_section(
    *,
    db: AsyncSession,
    user: User,
    section_id: uuid.UUID,
    name: str,
    user_read: bool,
    user_write: bool,
) -> KnowledgeSection:
    _require_admin(user)
    name = _section_name(name)
    if user_write and not user_read:
        raise ValidationError("Право записи требует права чтения")
    await queries.lock_storage(db)
    section = await queries.section(db, section_id, lock=True)
    if section is None:
        raise NotFoundError("Раздел не найден")
    if await queries.section_name_taken(db, name=name, excluded_id=section_id):
        raise ConflictError("Раздел с таким названием уже существует")
    section.name, section.user_read, section.user_write = name, user_read, user_write
    await db.commit()
    return section


async def collect_garbage(db: AsyncSession) -> int:
    async with db.begin_nested():
        await queries.lock_collection(db)
        await queries.lock_storage(db)
        referenced = await queries.referenced_objects(db)
        sections = await queries.section_ids(db)
        removed = await asyncio.to_thread(collect_objects, referenced, sections)
    await db.commit()
    return removed


async def remove_section(db: AsyncSession, *, user: User, section_id: uuid.UUID) -> None:
    _require_admin(user)
    await queries.lock_storage(db)
    if await queries.section(db, section_id, lock=True) is None:
        raise NotFoundError("Раздел не найден")
    await queries.delete_section(db, section_id)
    await db.commit()
    try:
        await collect_garbage(db)
    except OSError:
        await db.commit()
        logger.exception("knowledge_collection_pending", section_id=str(section_id))


async def maintain_storage(db: AsyncSession, *, user: User) -> int:
    _require_admin(user)
    await finish_changes(db, section_ids={section.id for section in await queries.sections(db)})
    return await collect_garbage(db)
