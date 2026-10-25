"""CRUD `mcp_servers` (раздел 3.1, 10.2 ТЗ) — административная часть
(раздел 15.5). Правило 3 CLAUDE.md/раздел 3.2: `has_stateful_resource=true`
с `isolation_mode` не заполненным (или `none`) запрещено валидацией API —
см. `services/mcp_validation.py`."""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from api.schemas import McpServerCreateRequest, McpServerResponse, McpServerUpdateRequest
from db.models.mcp import McpServer
from db.models.users import User
from db.session import get_session
from services.access import get_or_404
from services.crypto import encrypt
from services.integrity import ensure_mcp_server_deletable
from services.mcp_validation import normalize_mcp_server_isolation, validate_mcp_server_isolation

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


async def _get_mcp_server_or_404(db_session: AsyncSession, mcp_server_id: uuid.UUID) -> McpServer:
    return await get_or_404(
        db_session,
        McpServer,
        mcp_server_id,
        not_found=f"MCP-сервер {mcp_server_id} не найден",
    )


@router.post("", response_model=McpServerResponse, status_code=201)
async def create_mcp_server(
    body: McpServerCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> McpServer:
    validate_mcp_server_isolation(
        has_stateful_resource=body.has_stateful_resource,
        isolation_mode=body.isolation_mode,
        isolation_path_template=body.isolation_path_template,
    )
    isolation_mode, isolation_path_template = normalize_mcp_server_isolation(
        has_stateful_resource=body.has_stateful_resource,
        isolation_mode=body.isolation_mode,
        isolation_path_template=body.isolation_path_template,
    )
    mcp_server = McpServer(
        id=uuid.uuid4(),
        name=body.name,
        url=body.url,
        auth_type=body.auth_type,
        auth_config_encrypted=encrypt(body.auth_config),
        has_stateful_resource=body.has_stateful_resource,
        isolation_mode=isolation_mode,
        isolation_path_template=isolation_path_template,
    )
    db_session.add(mcp_server)
    await db_session.commit()
    return mcp_server


@router.get("", response_model=list[McpServerResponse])
async def list_mcp_servers(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[McpServer]:
    """
    Раздел 10.5, 19.2: список нужен любому пользователю для выбора серверов
    в своём шаблоне; в ответе нет данных авторизации. Изменения — только `admin`.
    """
    stmt = sa.select(McpServer).order_by(McpServer.name)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{mcp_server_id}", response_model=McpServerResponse)
async def get_mcp_server(
    mcp_server_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> McpServer:
    return await _get_mcp_server_or_404(db_session, mcp_server_id)


@router.patch("/{mcp_server_id}", response_model=McpServerResponse)
async def update_mcp_server(
    mcp_server_id: uuid.UUID,
    body: McpServerUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> McpServer:
    mcp_server = await _get_mcp_server_or_404(db_session, mcp_server_id)
    if body.name is not None:
        mcp_server.name = body.name
    if body.url is not None:
        mcp_server.url = body.url
    if body.auth_type is not None:
        mcp_server.auth_type = body.auth_type
    if body.auth_config is not None:
        mcp_server.auth_config_encrypted = encrypt(body.auth_config)
    if body.has_stateful_resource is not None:
        mcp_server.has_stateful_resource = body.has_stateful_resource
    if body.isolation_mode is not None:
        mcp_server.isolation_mode = body.isolation_mode
    if body.isolation_path_template is not None:
        mcp_server.isolation_path_template = body.isolation_path_template

    validate_mcp_server_isolation(
        has_stateful_resource=mcp_server.has_stateful_resource,
        isolation_mode=mcp_server.isolation_mode,
        isolation_path_template=mcp_server.isolation_path_template,
    )
    mcp_server.isolation_mode, mcp_server.isolation_path_template = normalize_mcp_server_isolation(
        has_stateful_resource=mcp_server.has_stateful_resource,
        isolation_mode=mcp_server.isolation_mode,
        isolation_path_template=mcp_server.isolation_path_template,
    )
    await db_session.commit()
    await db_session.refresh(mcp_server)
    return mcp_server


@router.delete("/{mcp_server_id}", status_code=204)
async def delete_mcp_server(
    mcp_server_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    mcp_server = await _get_mcp_server_or_404(db_session, mcp_server_id)
    await ensure_mcp_server_deletable(db_session, mcp_server_id)
    await db_session.delete(mcp_server)
    await db_session.commit()
