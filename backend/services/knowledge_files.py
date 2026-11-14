"""Версионирование файлов базы знаний с блокировкой раздела при изменениях."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.knowledge import KnowledgeEntry, KnowledgeSection, KnowledgeVersion
from db.models.users import User
from services.errors import ConflictError, NotFoundError
from services.knowledge_sections import require_section
from services.knowledge_storage import (
    read_knowledge_content,
    store_knowledge_content,
    validate_knowledge_path,
)


async def _check_tree_path(
    *,
    db: AsyncSession,
    section_id: uuid.UUID,
    path: str,
    is_directory: bool,
    excluded_ids: list[uuid.UUID],
) -> None:
    parts = path.split("/")
    ancestors = ["/".join(parts[:index]) for index in range(1, len(parts))]
    conflict = await db.scalar(
        sa.select(KnowledgeEntry.id)
        .where(
            KnowledgeEntry.section_id == section_id,
            KnowledgeEntry.id.not_in(excluded_ids),
            sa.or_(
                sa.and_(
                    KnowledgeEntry.path.in_(ancestors),
                    sa.or_(
                        KnowledgeEntry.is_directory.is_(False),
                        KnowledgeEntry.deleted_at.is_not(None),
                    ),
                ),
                sa.and_(
                    sa.literal(not is_directory),
                    KnowledgeEntry.path.startswith(path + "/", autoescape=True),
                ),
            ),
        )
        .limit(1)
    )
    if conflict is not None:
        raise ConflictError("Путь конфликтует с существующим файлом или папкой")


async def entry_content(
    db: AsyncSession, *, entry: KnowledgeEntry, version: int | None = None
) -> bytes:
    stored = await db.scalar(
        sa.select(KnowledgeVersion).where(
            KnowledgeVersion.entry_id == entry.id,
            KnowledgeVersion.version == (version or entry.version),
        )
    )
    if stored is None:
        raise NotFoundError("Версия файла не найдена")
    return await read_knowledge_content(stored.storage_key)


async def write_entry(
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
    validate_knowledge_path(path)
    await db.get(KnowledgeSection, section_id, with_for_update=True, populate_existing=True)
    await require_section(db, section_id=section_id, user=user, write=True)
    entry = await db.scalar(
        sa.select(KnowledgeEntry).where(
            KnowledgeEntry.section_id == section_id,
            KnowledgeEntry.path == path,
        )
    )
    if entry is not None:
        if entry.version != expected_version:
            raise ConflictError("Файл изменён. Перечитайте текущую версию перед сохранением")
        if entry.is_directory != is_directory or entry.deleted_at is not None:
            raise ConflictError("Путь занят папкой или удалённым файлом")
        entry.version += 1
    else:
        if expected_version != 0:
            raise ConflictError("Файл больше не существует")
        entry = KnowledgeEntry(
            section_id=section_id, path=path, version=1, is_directory=is_directory
        )
        db.add(entry)
        await db.flush()
    await _check_tree_path(
        db=db, section_id=section_id, path=path, is_directory=is_directory, excluded_ids=[entry.id]
    )
    key = await store_knowledge_content(content)
    db.add(
        KnowledgeVersion(
            entry_id=entry.id,
            version=entry.version,
            path=entry.path,
            storage_key=key,
            created_by=user.id,
            task_id=task_id,
        )
    )
    await db.flush()
    return entry


async def change_deleted(
    *,
    db: AsyncSession,
    user: User,
    entry_id: uuid.UUID,
    expected_version: int,
    deleted: bool,
    task_id: uuid.UUID | None = None,
) -> KnowledgeEntry:
    entry = await db.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise NotFoundError("Файл не найден")
    source_section_id = entry.section_id
    await db.get(KnowledgeSection, source_section_id, with_for_update=True)
    await require_section(db, section_id=source_section_id, user=user, write=True)
    await db.refresh(entry)
    if entry.section_id != source_section_id:
        raise ConflictError("Файл перемещён. Перечитайте его перед изменением")
    if entry.version != expected_version:
        raise ConflictError("Файл изменён. Перечитайте текущую версию")
    affected = [entry]
    if entry.is_directory:
        affected += list(
            await db.scalars(
                sa.select(KnowledgeEntry).where(
                    KnowledgeEntry.section_id == entry.section_id,
                    KnowledgeEntry.path.startswith(entry.path + "/", autoescape=True),
                    KnowledgeEntry.deleted_at == entry.deleted_at,
                )
            )
        )
    now = datetime.now(UTC)
    for item in affected:
        content = await entry_content(db, entry=item)
        item.version += 1
        item.deleted_at = now if deleted else None
        db.add(
            KnowledgeVersion(
                entry_id=item.id,
                version=item.version,
                path=item.path,
                operation="delete" if deleted else "restore",
                storage_key=await store_knowledge_content(content),
                created_by=user.id,
                task_id=task_id,
            )
        )
    await db.flush()
    return entry


async def move_entry(
    *,
    db: AsyncSession,
    user: User,
    entry_id: uuid.UUID,
    section_id: uuid.UUID,
    path: str,
    expected_version: int,
    task_id: uuid.UUID | None = None,
) -> KnowledgeEntry:
    validate_knowledge_path(path)
    entry = await db.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise NotFoundError("Файл не найден")
    source_section_id = entry.section_id
    for identifier in sorted({source_section_id, section_id}):
        await db.get(KnowledgeSection, identifier, with_for_update=True, populate_existing=True)
        await require_section(db, section_id=identifier, user=user, write=True)
    await db.refresh(entry)
    if entry.section_id != source_section_id:
        raise ConflictError("Файл перемещён. Перечитайте его перед изменением")
    if entry.version != expected_version or entry.deleted_at is not None:
        raise ConflictError("Файл изменён. Перечитайте текущую версию")
    if entry.section_id == section_id and path.startswith(entry.path + "/"):
        raise ConflictError("Нельзя перенести папку внутрь самой себя")
    affected = [entry]
    if entry.is_directory:
        affected += list(
            await db.scalars(
                sa.select(KnowledgeEntry).where(
                    KnowledgeEntry.section_id == entry.section_id,
                    KnowledgeEntry.path.startswith(entry.path + "/", autoescape=True),
                )
            )
        )
    prefix = entry.path
    ids = [item.id for item in affected]
    paths = {item.id: path + item.path[len(prefix) :] for item in affected}
    for new_path in paths.values():
        validate_knowledge_path(new_path)
    occupied = await db.scalar(
        sa.select(KnowledgeEntry.id)
        .where(
            KnowledgeEntry.section_id == section_id,
            KnowledgeEntry.path.in_(list(paths.values())),
            KnowledgeEntry.id.not_in(ids),
        )
        .limit(1)
    )
    if occupied is not None:
        raise ConflictError("Этот путь уже занят")
    for item in affected:
        await _check_tree_path(
            db=db,
            section_id=section_id,
            path=paths[item.id],
            is_directory=item.is_directory,
            excluded_ids=ids,
        )
    for item in affected:
        content = await entry_content(db, entry=item)
        item.section_id = section_id
        item.path = paths[item.id]
        item.version += 1
        db.add(
            KnowledgeVersion(
                entry_id=item.id,
                version=item.version,
                path=item.path,
                operation="move",
                storage_key=await store_knowledge_content(content),
                created_by=user.id,
                task_id=task_id,
            )
        )
    await db.flush()
    return entry
