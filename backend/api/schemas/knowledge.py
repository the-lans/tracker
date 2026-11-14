"""
Схемы REST API базы знаний.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from services.knowledge_sections import MAX_SECTION_NAME_LENGTH
from services.knowledge_storage import MAX_KNOWLEDGE_PATH_LENGTH


class SectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_SECTION_NAME_LENGTH)
    user_read: bool = False
    user_write: bool = False


class SectionResponse(SectionRequest):
    publication_pending: bool = True
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class FileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=MAX_KNOWLEDGE_PATH_LENGTH)
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


class VersionResponse(BaseModel):
    operation: str
    path: str | None
    model_config = ConfigDict(from_attributes=True)
    version: int
    created_at: datetime
    created_by: uuid.UUID
    task_id: uuid.UUID | None


class MoveRequest(BaseModel):
    section_id: uuid.UUID
    path: str = Field(min_length=1, max_length=MAX_KNOWLEDGE_PATH_LENGTH)
    expected_version: int = Field(ge=1)
