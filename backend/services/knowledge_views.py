"""Обновляемое представление разрешённых файлов для чтения из контейнера."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.knowledge import KnowledgeEntry, KnowledgeSection
from db.models.users import User
from services.docker_mounts import mount_args
from services.knowledge_files import entry_content
from services.knowledge_sections import KnowledgeSectionSnapshot, section_snapshot
from services.knowledge_storage import knowledge_root, validate_knowledge_path


def _publish(root: Path, files: dict[str, bytes | None]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    expected = set(files)
    for relative, content in files.items():
        validate_knowledge_path(relative)
        target = root / relative
        if content is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(".tracker-" + uuid.uuid4().hex)
            temporary.write_bytes(content)
            os.replace(temporary, target)
        parent = Path(relative).parent
        while parent != Path("."):
            expected.add(parent.as_posix())
            parent = parent.parent
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.relative_to(root).as_posix() not in expected:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()


async def publish_section(db: AsyncSession, *, section_id: uuid.UUID) -> None:
    section = await db.get(
        KnowledgeSection, section_id, with_for_update=True, populate_existing=True
    )
    if section is None:
        return
    entries = list(
        await db.scalars(
            sa.select(KnowledgeEntry)
            .where(
                KnowledgeEntry.section_id == section_id,
                KnowledgeEntry.deleted_at.is_(None),
            )
            .order_by(KnowledgeEntry.path)
        )
    )
    files = {
        entry.path: None if entry.is_directory else await entry_content(db, entry=entry)
        for entry in entries
    }
    await asyncio.to_thread(_publish, knowledge_root() / "views" / str(section_id), files)
    await db.commit()


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


async def clear_section_view(section_id: uuid.UUID) -> None:
    await asyncio.to_thread(_publish, knowledge_root() / "views" / str(section_id), {})
