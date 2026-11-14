"""
HTTP-интерфейс базы знаний: схемы, вызовы сервисов, сериализация.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import (
    DeletedRequest,
    EntryResponse,
    FileRequest,
    MoveRequest,
    SectionRequest,
    SectionResponse,
    VersionResponse,
)
from db.models.users import User
from db.session import get_session
from services import knowledge_admin as admin
from services import knowledge_commands as commands
from services import knowledge_reader as reader
from services.knowledge_files import entry_content
from services.knowledge_sections import list_sections
from services.knowledge_storage import MAX_KNOWLEDGE_FILE_BYTES

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
Db = Annotated[AsyncSession, Depends(get_session)]
Actor = Annotated[User, Depends(get_current_user)]


@router.get("/sections", response_model=list[SectionResponse])
async def sections(db: Db, user: Actor) -> object:
    return await list_sections(db, user=user)


@router.post("/sections", response_model=SectionResponse, status_code=201)
async def add_section(body: SectionRequest, db: Db, user: Actor) -> object:
    return await admin.create_section(db=db, user=user, **body.model_dump())


@router.patch("/sections/{section_id}", response_model=SectionResponse)
async def edit_section(section_id: uuid.UUID, body: SectionRequest, db: Db, user: Actor) -> object:
    return await admin.edit_section(db=db, user=user, section_id=section_id, **body.model_dump())


@router.delete("/sections/{section_id}", status_code=204)
async def remove_section(section_id: uuid.UUID, db: Db, user: Actor) -> None:
    await admin.remove_section(db, user=user, section_id=section_id)


@router.post("/maintenance")
async def maintenance(db: Db, user: Actor) -> dict[str, int]:
    return {"removed_objects": await admin.maintain_storage(db, user=user)}


@router.get("/sections/{section_id}/entries", response_model=list[EntryResponse])
async def entries(section_id: uuid.UUID, db: Db, user: Actor) -> object:
    return await reader.list_entries(db, user=user, section_id=section_id)


@router.put("/sections/{section_id}/entries", response_model=EntryResponse)
async def save_file(section_id: uuid.UUID, body: FileRequest, db: Db, user: Actor) -> object:
    return await commands.save(
        db=db,
        user=user,
        section_id=section_id,
        path=body.path,
        content=body.content.encode(),
        expected_version=body.expected_version,
        is_directory=body.is_directory,
    )


@router.get("/entries/{entry_id}/content")
async def content(
    entry_id: uuid.UUID, db: Db, user: Actor, version: int | None = None
) -> dict[str, str | int]:
    return await reader.text_content(db, user=user, entry_id=entry_id, version=version)


@router.patch("/entries/{entry_id}/deleted", response_model=EntryResponse)
async def deleted(entry_id: uuid.UUID, body: DeletedRequest, db: Db, user: Actor) -> object:
    return await commands.set_deleted(db=db, user=user, entry_id=entry_id, **body.model_dump())


@router.get("/entries/{entry_id}/history", response_model=list[VersionResponse])
async def history(entry_id: uuid.UUID, db: Db, user: Actor) -> object:
    return await reader.entry_history(db, user=user, entry_id=entry_id)


@router.patch("/entries/{entry_id}/location", response_model=EntryResponse)
async def move(entry_id: uuid.UUID, body: MoveRequest, db: Db, user: Actor) -> object:
    return await commands.move(db=db, user=user, entry_id=entry_id, **body.model_dump())


@router.get("/entries/{entry_id}/download")
async def download(entry_id: uuid.UUID, db: Db, user: Actor) -> Response:
    entry = await reader.readable_entry(db, user=user, entry_id=entry_id)
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
    return await commands.save(
        db=db,
        user=user,
        section_id=section_id,
        path=path,
        content=content,
        expected_version=expected_version,
    )


@router.get("/sections/{section_id}/search", response_model=list[EntryResponse])
async def search(section_id: uuid.UUID, query: str, db: Db, user: Actor) -> object:
    return await reader.search_entries(db, user=user, section_id=section_id, query=query)
