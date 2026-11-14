"""
Прикладные операции с файлами, версиями и деревом базы знаний.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import KnowledgeOperation
from db.models.knowledge import KnowledgeEntry, KnowledgeVersion
from db.models.users import User
from db.queries import knowledge as queries
from services.errors import ConflictError, NotFoundError
from services.knowledge_sections import require_section
from services.knowledge_storage import (
    read_knowledge_content,
    store_knowledge_content,
    validate_knowledge_path,
)


def _ancestors(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[:index]) for index in range(1, len(parts))]


async def _check_tree_path(
    *,
    db: AsyncSession,
    section_id: uuid.UUID,
    path: str,
    is_directory: bool,
    excluded_ids: list[uuid.UUID],
) -> None:
    if await queries.tree_conflict(
        db=db,
        section_id=section_id,
        path=path,
        ancestors=_ancestors(path),
        is_directory=is_directory,
        excluded_ids=excluded_ids,
    ):
        raise ConflictError("Путь конфликтует с существующим файлом или папкой")


async def _storage_key(db: AsyncSession, entry: KnowledgeEntry, version: int | None = None) -> str:
    key = await queries.version_key(
        db, entry_id=entry.id, version=entry.version if version is None else version
    )
    if key is None:
        raise NotFoundError("Версия файла не найдена")
    return key


async def entry_content(
    db: AsyncSession, *, entry: KnowledgeEntry, version: int | None = None
) -> bytes:
    return await read_knowledge_content(await _storage_key(db, entry, version))


async def _lock_sections(db: AsyncSession, *, user: User, ids: set[uuid.UUID]) -> None:
    await queries.lock_storage(db)
    for identifier in sorted(ids):
        section = await queries.section(db, identifier, lock=True)
        await require_section(db, section_id=identifier, user=user, write=True)
        assert section is not None
        section.publication_pending = True


def _record_version(
    *,
    db: AsyncSession,
    entry: KnowledgeEntry,
    key: str,
    user: User,
    operation: KnowledgeOperation,
    task_id: uuid.UUID | None,
) -> None:
    db.add(
        KnowledgeVersion(
            entry_id=entry.id,
            version=entry.version,
            path=entry.path,
            storage_key=key,
            created_by=user.id,
            operation=operation.value,
            task_id=task_id,
        )
    )


async def _locked_entry(
    *,
    db: AsyncSession,
    user: User,
    entry_id: uuid.UUID,
    expected_version: int,
    target_section_id: uuid.UUID | None = None,
) -> KnowledgeEntry:
    entry = await queries.entry(db, entry_id)
    if entry is None:
        raise NotFoundError("Файл не найден")
    original = entry.section_id
    await _lock_sections(db, user=user, ids={original, target_section_id or original})
    await db.refresh(entry)
    if entry.section_id != original or entry.version != expected_version:
        raise ConflictError("Файл изменён или перемещён. Перечитайте текущую версию")
    return entry


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
    await _lock_sections(db, user=user, ids={section_id})
    entry = await queries.entry_at(db, section_id=section_id, path=path)
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
    _record_version(
        db=db, entry=entry, key=key, user=user, operation=KnowledgeOperation.SAVE, task_id=task_id
    )
    await db.flush()
    return entry


async def _restore_parents(
    db: AsyncSession, *, entry: KnowledgeEntry, user: User, task_id: uuid.UUID | None
) -> None:
    for path in _ancestors(entry.path):
        parent = await queries.entry_at(db, section_id=entry.section_id, path=path)
        if parent is None:
            continue
        if not parent.is_directory:
            raise ConflictError("Родительский путь занят файлом")
        if parent.deleted_at is not None:
            key = await _storage_key(db, parent)
            parent.version += 1
            parent.deleted_at = None
            _record_version(
                db=db,
                entry=parent,
                key=key,
                user=user,
                operation=KnowledgeOperation.RESTORE,
                task_id=task_id,
            )


async def change_deleted(
    *,
    db: AsyncSession,
    user: User,
    entry_id: uuid.UUID,
    expected_version: int,
    deleted: bool,
    task_id: uuid.UUID | None = None,
) -> KnowledgeEntry:
    entry = await _locked_entry(
        db=db, user=user, entry_id=entry_id, expected_version=expected_version
    )
    affected = [entry]
    if entry.is_directory:
        affected += [
            child
            for child in await queries.descendants(db, section_id=entry.section_id, path=entry.path)
            if child.deleted_at == entry.deleted_at
        ]
    if not deleted:
        await _restore_parents(db, entry=entry, user=user, task_id=task_id)
    now = datetime.now(UTC)
    for item in affected:
        key = await _storage_key(db, item)
        item.version += 1
        item.deleted_at = now if deleted else None
        _record_version(
            db=db,
            entry=item,
            key=key,
            user=user,
            operation=KnowledgeOperation.DELETE if deleted else KnowledgeOperation.RESTORE,
            task_id=task_id,
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
    entry = await _locked_entry(
        db=db,
        user=user,
        entry_id=entry_id,
        expected_version=expected_version,
        target_section_id=section_id,
    )
    if entry.deleted_at is not None:
        raise ConflictError("Сначала восстановите файл из корзины")
    if entry.section_id == section_id and path.startswith(entry.path + "/"):
        raise ConflictError("Нельзя перенести папку внутрь самой себя")
    affected = [entry]
    if entry.is_directory:
        affected += await queries.descendants(db, section_id=entry.section_id, path=entry.path)
    ids = [item.id for item in affected]
    paths = {item.id: path + item.path[len(entry.path) :] for item in affected}
    if await queries.occupied_paths(
        db, section_id=section_id, paths=list(paths.values()), excluded_ids=ids
    ):
        raise ConflictError("Этот путь уже занят")
    for item in affected:
        validate_knowledge_path(paths[item.id])
        await _check_tree_path(
            db=db,
            section_id=section_id,
            path=paths[item.id],
            is_directory=item.is_directory,
            excluded_ids=ids,
        )
    for item in affected:
        key = await _storage_key(db, item)
        item.section_id = section_id
        item.path = paths[item.id]
        item.version += 1
        _record_version(
            db=db,
            entry=item,
            key=key,
            user=user,
            operation=KnowledgeOperation.MOVE,
            task_id=task_id,
        )
    await db.flush()
    return entry
