"""
Чтение, история и поиск с проверкой доступа к базе знаний.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.knowledge import KnowledgeEntry, KnowledgeVersion
from db.models.users import User
from db.queries import knowledge as queries
from services.errors import NotFoundError, ValidationError
from services.knowledge_files import entry_content
from services.knowledge_sections import require_section


async def readable_entry(db: AsyncSession, *, user: User, entry_id: uuid.UUID) -> KnowledgeEntry:
    entry = await queries.entry(db, entry_id)
    if entry is None:
        raise NotFoundError("Файл не найден")
    await require_section(db, section_id=entry.section_id, user=user)
    return entry


async def list_entries(
    db: AsyncSession, *, user: User, section_id: uuid.UUID
) -> list[KnowledgeEntry]:
    await require_section(db, section_id=section_id, user=user)
    return await queries.entries(db, section_ids=[section_id])


async def text_content(
    db: AsyncSession, *, user: User, entry_id: uuid.UUID, version: int | None = None
) -> dict[str, str | int]:
    entry = await readable_entry(db, user=user, entry_id=entry_id)
    try:
        text = (await entry_content(db, entry=entry, version=version)).decode()
    except UnicodeDecodeError as exc:
        raise ValidationError("Для этого файла доступно скачивание") from exc
    return {"content": text, "version": entry.version if version is None else version}


async def entry_history(
    db: AsyncSession, *, user: User, entry_id: uuid.UUID
) -> list[KnowledgeVersion]:
    await readable_entry(db, user=user, entry_id=entry_id)
    return await queries.history(db, entry_id)


async def search_entries(
    db: AsyncSession, *, user: User, section_id: uuid.UUID, query: str
) -> list[KnowledgeEntry]:
    await require_section(db, section_id=section_id, user=user)
    matches = []
    needle = query.casefold()
    for entry in await queries.entries(db, section_ids=[section_id], live_only=True):
        if entry.is_directory:
            continue
        if needle in entry.path.casefold():
            matches.append(entry)
            continue
        try:
            text = (await entry_content(db, entry=entry)).decode()
        except UnicodeDecodeError:
            continue
        if needle in text.casefold():
            matches.append(entry)
    return matches
