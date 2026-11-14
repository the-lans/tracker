"""
Инкрементальное представление файлов без загрузки содержимого в память.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app_logging.config import get_logger
from db.models.users import User
from db.queries import knowledge as queries
from services.docker_mounts import mount_args
from services.knowledge_objects import KnowledgeProjection, KnowledgeSectionSnapshot
from services.knowledge_projection import KnowledgeProjectionPublisher
from services.knowledge_sections import section_snapshot
from services.knowledge_storage import knowledge_root

logger = get_logger("knowledge_views")


def _publish(root: Path, files: list[KnowledgeProjection]) -> None:
    KnowledgeProjectionPublisher(root).publish(files)


async def _publish_section(db: AsyncSession, *, section_id: uuid.UUID) -> None:
    await queries.lock_storage(db)
    section = await queries.section(db, section_id, lock=True)
    if section is None:
        return
    files = [
        KnowledgeProjection(path=path, storage_key=None if directory else key)
        for path, directory, key in await queries.projection(db, section_id)
    ]
    await asyncio.to_thread(_publish, knowledge_root() / "views" / str(section_id), files)
    section.publication_pending = False


async def publish_section(db: AsyncSession, *, section_id: uuid.UUID) -> None:
    async with db.begin_nested():
        await _publish_section(db, section_id=section_id)
    await db.commit()


async def finish_changes(db: AsyncSession, *, section_ids: set[uuid.UUID]) -> bool:
    await db.commit()
    synchronized = True
    for section_id in sorted(section_ids):
        try:
            await publish_section(db, section_id=section_id)
        except OSError:
            await db.commit()
            logger.exception("knowledge_publication_pending", section_id=str(section_id))
            synchronized = False
    return synchronized


async def knowledge_mounts(
    db: AsyncSession, *, user: User, sections: list[KnowledgeSectionSnapshot] | None = None
) -> list[str]:
    result: list[str] = []
    for section in sections if sections is not None else await section_snapshot(db, user=user):
        await publish_section(db, section_id=section.id)
        path = knowledge_root() / "views" / str(section.id)
        args = await mount_args(path, knowledge_root())
        destination = "/workspace/knowledge/" + str(section.id)
        if args[0] == "--mount":
            args[1] = args[1].replace(f"dst={path}", f"dst={destination}") + ",readonly"
        else:
            source = args[1].rsplit(":", 2)[0]
            args[1] = f"{source}:{destination}:ro"
        result.extend(args)
    return result
