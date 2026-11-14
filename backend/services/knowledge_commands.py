"""
Единые команды записи для HTTP и MCP, включая завершение публикации.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.knowledge import KnowledgeEntry
from db.models.users import User
from db.queries import knowledge as queries
from services.errors import NotFoundError
from services.knowledge_files import change_deleted, move_entry, write_entry
from services.knowledge_views import finish_changes


async def save(
    *,
    db: AsyncSession,
    user: User,
    section_id: uuid.UUID,
    path: str,
    content: bytes,
    expected_version: int,
    is_directory: bool = False,
    task_id: uuid.UUID | None = None,
) -> KnowledgeEntry:
    entry = await write_entry(
        db=db,
        user=user,
        section_id=section_id,
        path=path,
        content=content,
        expected_version=expected_version,
        is_directory=is_directory,
        task_id=task_id,
    )
    await finish_changes(db, section_ids={section_id})
    return entry


async def set_deleted(
    *,
    db: AsyncSession,
    user: User,
    entry_id: uuid.UUID,
    expected_version: int,
    deleted: bool,
    task_id: uuid.UUID | None = None,
) -> KnowledgeEntry:
    entry = await change_deleted(
        db=db,
        user=user,
        entry_id=entry_id,
        expected_version=expected_version,
        deleted=deleted,
        task_id=task_id,
    )
    section_id = entry.section_id
    await finish_changes(db, section_ids={section_id})
    return entry


async def move(
    *,
    db: AsyncSession,
    user: User,
    entry_id: uuid.UUID,
    section_id: uuid.UUID,
    path: str,
    expected_version: int,
    task_id: uuid.UUID | None = None,
) -> KnowledgeEntry:
    previous = await queries.entry(db, entry_id)
    if previous is None:
        raise NotFoundError("Файл не найден")
    source = previous.section_id
    entry = await move_entry(
        db=db,
        user=user,
        entry_id=entry_id,
        section_id=section_id,
        path=path,
        expected_version=expected_version,
        task_id=task_id,
    )
    await finish_changes(db, section_ids={source, section_id})
    return entry
