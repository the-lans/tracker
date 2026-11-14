"""API общего пространства знаний."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from db.models.enums import UserRole
from db.models.knowledge import KnowledgeEntry, KnowledgeSection, KnowledgeVersion
from db.models.users import User
from db.session import get_session
from services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from services.knowledge_files import change_deleted, entry_content, move_entry, write_entry
from services.knowledge_sections import create_section, list_sections, require_section
from services.knowledge_storage import MAX_KNOWLEDGE_FILE_BYTES
from services.knowledge_views import clear_section_view, publish_section

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
Db = Annotated[AsyncSession, Depends(get_session)]
Actor = Annotated[User, Depends(get_current_user)]


class SectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    user_read: bool = False
    user_write: bool = False


class SectionResponse(SectionRequest):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class FileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = ""
    expected_version: int = Field(ge=0)
    is_directory: bool = False


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    section_id: uuid.UUID
    path: str
    version: int
    is_directory: bool
    deleted_at: datetime | None


class DeletedRequest(BaseModel):
    expected_version: int = Field(ge=1)
    deleted: bool


@router.get("/sections", response_model=list[SectionResponse])
async def sections(db: Db, user: Actor) -> object:
    return await list_sections(db, user=user)


@router.post("/sections", response_model=SectionResponse, status_code=201)
async def add_section(body: SectionRequest, db: Db, user: Actor) -> object:
    section = await create_section(db, user=user, **body.model_dump())
    await db.commit()
    return section


@router.get("/sections/{section_id}/entries", response_model=list[EntryResponse])
async def entries(section_id: uuid.UUID, db: Db, user: Actor) -> object:
    await require_section(db, section_id=section_id, user=user)
    return list(
        await db.scalars(
            sa.select(KnowledgeEntry)
            .where(
                KnowledgeEntry.section_id == section_id,
            )
            .order_by(KnowledgeEntry.path)
        )
    )


@router.put("/sections/{section_id}/entries", response_model=EntryResponse)
async def save_file(section_id: uuid.UUID, body: FileRequest, db: Db, user: Actor) -> object:
    entry = await write_entry(
        db=db,
        user=user,
        section_id=section_id,
        path=body.path,
        content=body.content.encode(),
        expected_version=body.expected_version,
        is_directory=body.is_directory,
    )
    await db.commit()
    await publish_section(db, section_id=entry.section_id)
    return entry


@router.get("/entries/{entry_id}/content")
async def content(
    entry_id: uuid.UUID, db: Db, user: Actor, version: int | None = None
) -> dict[str, str | int]:
    entry = await db.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise NotFoundError("Файл не найден")
    await require_section(db, section_id=entry.section_id, user=user)
    try:
        text = (await entry_content(db, entry=entry, version=version)).decode()
    except UnicodeDecodeError as exc:
        raise ValidationError("Для этого файла доступно скачивание") from exc
    return {"content": text, "version": version if version is not None else entry.version}


@router.patch("/entries/{entry_id}/deleted", response_model=EntryResponse)
async def deleted(entry_id: uuid.UUID, body: DeletedRequest, db: Db, user: Actor) -> object:
    entry = await change_deleted(db=db, user=user, entry_id=entry_id, **body.model_dump())
    await db.commit()
    await publish_section(db, section_id=entry.section_id)
    return entry


@router.patch("/sections/{section_id}", response_model=SectionResponse)
async def edit_section(section_id: uuid.UUID, body: SectionRequest, db: Db, user: Actor) -> object:
    if user.role is not UserRole.ADMIN:
        raise ForbiddenError("Настройки раздела доступны администратору")
    section = await db.get(KnowledgeSection, section_id, with_for_update=True)
    if section is None:
        raise NotFoundError("Раздел не найден")
    if body.user_write and not body.user_read:
        raise ValidationError("Право записи требует права чтения")
    duplicate = await db.scalar(
        sa.select(KnowledgeSection.id)
        .where(
            KnowledgeSection.name == body.name.strip(),
            KnowledgeSection.id != section_id,
        )
        .limit(1)
    )
    if duplicate is not None:
        raise ConflictError("Раздел с таким названием уже существует")
    section.name = body.name.strip()
    if not section.name:
        raise ValidationError("Название не может быть пустым")
    section.user_read = body.user_read
    section.user_write = body.user_write
    await db.commit()
    return section


class VersionResponse(BaseModel):
    operation: str
    path: str | None
    model_config = ConfigDict(from_attributes=True)
    version: int
    created_at: datetime
    created_by: uuid.UUID
    task_id: uuid.UUID | None


@router.get("/entries/{entry_id}/history", response_model=list[VersionResponse])
async def history(entry_id: uuid.UUID, db: Db, user: Actor) -> object:
    entry = await db.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise NotFoundError("Файл не найден")
    await require_section(db, section_id=entry.section_id, user=user)
    return list(
        await db.scalars(
            sa.select(KnowledgeVersion)
            .where(
                KnowledgeVersion.entry_id == entry_id,
            )
            .order_by(KnowledgeVersion.version.desc())
        )
    )


class MoveRequest(BaseModel):
    section_id: uuid.UUID
    path: str = Field(min_length=1, max_length=1024)
    expected_version: int = Field(ge=1)


@router.patch("/entries/{entry_id}/location", response_model=EntryResponse)
async def move(entry_id: uuid.UUID, body: MoveRequest, db: Db, user: Actor) -> object:
    previous = await db.get(KnowledgeEntry, entry_id)
    previous_section_id = previous.section_id if previous else None
    entry = await move_entry(db=db, user=user, entry_id=entry_id, **body.model_dump())
    await db.commit()
    await publish_section(db, section_id=entry.section_id)
    if previous_section_id is not None and previous_section_id != entry.section_id:
        await publish_section(db, section_id=previous_section_id)
    return entry


@router.get("/entries/{entry_id}/download")
async def download(entry_id: uuid.UUID, db: Db, user: Actor) -> Response:
    entry = await db.get(KnowledgeEntry, entry_id)
    if entry is None:
        raise NotFoundError("Файл не найден")
    await require_section(db, section_id=entry.section_id, user=user)
    return Response(await entry_content(db, entry=entry), media_type="application/octet-stream")


@router.post("/sections/{section_id}/upload", response_model=EntryResponse)
async def upload(
    *,
    section_id: uuid.UUID,
    db: Db,
    user: Actor,
    file: UploadFile,
    path: str,
    expected_version: int = 0,
) -> object:
    content = await file.read(MAX_KNOWLEDGE_FILE_BYTES + 1)
    entry = await write_entry(
        db=db,
        user=user,
        section_id=section_id,
        path=path,
        content=content,
        expected_version=expected_version,
    )
    await db.commit()
    await publish_section(db, section_id=entry.section_id)
    return entry


@router.get("/sections/{section_id}/search", response_model=list[EntryResponse])
async def search(section_id: uuid.UUID, query: str, db: Db, user: Actor) -> object:
    await require_section(db, section_id=section_id, user=user)
    candidates = list(
        await db.scalars(
            sa.select(KnowledgeEntry)
            .where(
                KnowledgeEntry.section_id == section_id,
                KnowledgeEntry.deleted_at.is_(None),
                KnowledgeEntry.is_directory.is_(False),
            )
            .order_by(KnowledgeEntry.path)
        )
    )
    matches = []
    needle = query.casefold()
    for entry in candidates:
        if needle in entry.path.casefold():
            matches.append(entry)
        else:
            try:
                text = (await entry_content(db, entry=entry)).decode()
            except UnicodeDecodeError:
                continue
            if needle in text.casefold():
                matches.append(entry)
    return matches


@router.delete("/sections/{section_id}", status_code=204)
async def remove_section(section_id: uuid.UUID, db: Db, user: Actor) -> None:
    if user.role is not UserRole.ADMIN:
        raise ForbiddenError("Удалять разделы может только администратор")
    section = await db.get(KnowledgeSection, section_id, with_for_update=True)
    if section is None:
        raise NotFoundError("Раздел не найден")
    entry_ids = sa.select(KnowledgeEntry.id).where(KnowledgeEntry.section_id == section_id)
    await db.execute(sa.delete(KnowledgeVersion).where(KnowledgeVersion.entry_id.in_(entry_ids)))
    await db.execute(sa.delete(KnowledgeEntry).where(KnowledgeEntry.section_id == section_id))
    await db.delete(section)
    await db.commit()
    await clear_section_view(section_id)
