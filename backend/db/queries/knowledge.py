"""
Запросы базы знаний без бизнес-решений и фиксации транзакций.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from db.models.knowledge import KnowledgeEntry, KnowledgeSection, KnowledgeVersion
from db.models.users import User

_STORAGE_LOCK_ID = 1296976967
_COLLECTION_LOCK_ID = 1296976968


async def lock_storage(db: AsyncSession) -> None:
    await db.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": _STORAGE_LOCK_ID})


async def section(
    db: AsyncSession, section_id: uuid.UUID, *, lock: bool = False
) -> KnowledgeSection | None:
    return await db.get(KnowledgeSection, section_id, with_for_update=lock, populate_existing=True)


async def sections(db: AsyncSession, *, readable_only: bool = False) -> list[KnowledgeSection]:
    query = sa.select(KnowledgeSection).order_by(KnowledgeSection.name)
    if readable_only:
        query = query.where(KnowledgeSection.user_read.is_(True))
    return list(await db.scalars(query))


async def entry(db: AsyncSession, entry_id: uuid.UUID) -> KnowledgeEntry | None:
    return await db.get(KnowledgeEntry, entry_id)


async def entry_at(db: AsyncSession, *, section_id: uuid.UUID, path: str) -> KnowledgeEntry | None:
    return await db.scalar(
        sa.select(KnowledgeEntry).where(
            KnowledgeEntry.section_id == section_id, KnowledgeEntry.path == path
        )
    )


async def entries(
    db: AsyncSession, *, section_ids: Sequence[uuid.UUID], live_only: bool = False
) -> list[KnowledgeEntry]:
    query = (
        sa.select(KnowledgeEntry)
        .where(KnowledgeEntry.section_id.in_(section_ids))
        .order_by(KnowledgeEntry.path)
    )
    if live_only:
        query = query.where(KnowledgeEntry.deleted_at.is_(None))
    return list(await db.scalars(query))


async def descendants(
    db: AsyncSession, *, section_id: uuid.UUID, path: str
) -> list[KnowledgeEntry]:
    return list(
        await db.scalars(
            sa.select(KnowledgeEntry)
            .where(
                KnowledgeEntry.section_id == section_id,
                KnowledgeEntry.path.startswith(path + "/", autoescape=True),
            )
            .order_by(KnowledgeEntry.path)
        )
    )


async def version_key(db: AsyncSession, *, entry_id: uuid.UUID, version: int) -> str | None:
    return await db.scalar(
        sa.select(KnowledgeVersion.storage_key).where(
            KnowledgeVersion.entry_id == entry_id, KnowledgeVersion.version == version
        )
    )


async def history(db: AsyncSession, entry_id: uuid.UUID) -> list[KnowledgeVersion]:
    return list(
        await db.scalars(
            sa.select(KnowledgeVersion)
            .where(KnowledgeVersion.entry_id == entry_id)
            .order_by(KnowledgeVersion.version.desc())
        )
    )


async def tree_conflict(
    *,
    db: AsyncSession,
    section_id: uuid.UUID,
    path: str,
    ancestors: list[str],
    is_directory: bool,
    excluded_ids: list[uuid.UUID],
) -> bool:
    return bool(
        await db.scalar(
            sa.select(
                sa.exists().where(
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
            )
        )
    )


async def occupied_paths(
    db: AsyncSession, *, section_id: uuid.UUID, paths: list[str], excluded_ids: list[uuid.UUID]
) -> bool:
    return bool(
        await db.scalar(
            sa.select(
                sa.exists().where(
                    KnowledgeEntry.section_id == section_id,
                    KnowledgeEntry.path.in_(paths),
                    KnowledgeEntry.id.not_in(excluded_ids),
                )
            )
        )
    )


async def projection(db: AsyncSession, section_id: uuid.UUID) -> list[tuple[str, bool, str]]:
    rows = await db.execute(
        sa.select(KnowledgeEntry.path, KnowledgeEntry.is_directory, KnowledgeVersion.storage_key)
        .join(
            KnowledgeVersion,
            sa.and_(
                KnowledgeVersion.entry_id == KnowledgeEntry.id,
                KnowledgeVersion.version == KnowledgeEntry.version,
            ),
        )
        .where(KnowledgeEntry.section_id == section_id, KnowledgeEntry.deleted_at.is_(None))
        .order_by(KnowledgeEntry.path)
    )
    return [(path, directory, key) for path, directory, key in rows]


async def section_name_taken(
    db: AsyncSession, *, name: str, excluded_id: uuid.UUID | None = None
) -> bool:
    query = sa.select(KnowledgeSection.id).where(KnowledgeSection.name == name)
    if excluded_id is not None:
        query = query.where(KnowledgeSection.id != excluded_id)
    return await db.scalar(query.limit(1)) is not None


async def delete_section(db: AsyncSession, section_id: uuid.UUID) -> None:
    ids = sa.select(KnowledgeEntry.id).where(KnowledgeEntry.section_id == section_id)
    await db.execute(sa.delete(KnowledgeVersion).where(KnowledgeVersion.entry_id.in_(ids)))
    await db.execute(sa.delete(KnowledgeEntry).where(KnowledgeEntry.section_id == section_id))
    await db.execute(sa.delete(KnowledgeSection).where(KnowledgeSection.id == section_id))


async def referenced_objects(db: AsyncSession) -> set[str]:
    return {
        uuid.UUID(key).hex
        for key in await db.scalars(sa.select(KnowledgeVersion.storage_key).distinct())
    }


async def section_ids(db: AsyncSession) -> set[str]:
    return {str(identifier) for identifier in await db.scalars(sa.select(KnowledgeSection.id))}


async def lock_collection(db: AsyncSession) -> None:
    await db.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": _COLLECTION_LOCK_ID})


async def protect_collection(connection: AsyncConnection) -> None:
    await connection.execute(
        sa.text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": _COLLECTION_LOCK_ID}
    )


async def owner(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)
