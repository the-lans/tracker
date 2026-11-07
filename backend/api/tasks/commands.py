"""Каталог и запуск команд библиотеки в контексте задачи."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import ManualRequestResponse
from api.tasks.common import TASKS_PREFIX, TASKS_TAGS, get_task_or_404, publish_signal
from db.models.enums import NodeType
from db.models.users import User
from db.session import get_session
from services.command_arguments import MAX_COMMAND_INPUT_NAME_LENGTH, MAX_COMMAND_LENGTH
from services.library_commands import enqueue_command, list_commands, preview_command

router = APIRouter(prefix=TASKS_PREFIX, tags=TASKS_TAGS)
DEFAULT_COMMAND_PAGE_SIZE = 50
MAX_COMMAND_PAGE_SIZE = 100

Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


class CommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slash_name: str
    argument_hint: str | None
    description: str | None
    node_type: NodeType
    revision: int


class CommandPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invocation: str = Field(min_length=1, max_length=MAX_COMMAND_LENGTH)


class CommandPreviewResponse(BaseModel):
    rendered_text: str


class CommandRunRequest(CommandPreviewRequest):
    client_request_id: uuid.UUID


@router.get("/{task_id}/commands", response_model=list[CommandResponse])
async def get_commands(
    *,
    task_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    prefix: str = Query(default="", max_length=MAX_COMMAND_INPUT_NAME_LENGTH),
    limit: int = Query(default=DEFAULT_COMMAND_PAGE_SIZE, ge=1, le=MAX_COMMAND_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> list[CommandResponse]:
    task = await get_task_or_404(session, task_id, user)
    rows = await list_commands(
        session, owner_id=task.created_by, prefix=prefix, limit=limit, offset=offset
    )
    return [CommandResponse.model_validate(row) for row in rows]


@router.post("/{task_id}/commands/run", response_model=ManualRequestResponse, status_code=201)
async def run_command(
    task_id: uuid.UUID,
    body: CommandRunRequest,
    session: Session,
    user: CurrentUser,
) -> ManualRequestResponse:
    task = await get_task_or_404(session, task_id, user)
    request = await enqueue_command(
        session,
        task=task,
        requested_by=user.id,
        invocation=body.invocation,
        client_request_id=body.client_request_id,
    )
    await publish_signal(task_id)
    return ManualRequestResponse.model_validate(request)


@router.post("/{task_id}/commands/preview", response_model=CommandPreviewResponse)
async def preview_task_command(
    task_id: uuid.UUID,
    body: CommandPreviewRequest,
    session: Session,
    user: CurrentUser,
) -> CommandPreviewResponse:
    task = await get_task_or_404(session, task_id, user)
    return CommandPreviewResponse(
        rendered_text=await preview_command(
            session,
            task=task,
            invocation=body.invocation,
        )
    )
