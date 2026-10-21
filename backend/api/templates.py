"""CRUD `templates` (раздел 3.1 ТЗ) — набор файлов + связанные MCP-серверы."""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import TemplateCreateRequest, TemplateResponse, TemplateUpdateRequest
from db.models.repositories import Template, TemplateMcpServer
from db.models.users import User
from db.session import get_session
from services.access import get_template_for_user, owner_filter
from services.errors import ConflictError

router = APIRouter(prefix="/templates", tags=["templates"])


async def _get_template_or_404(
    db_session: AsyncSession,
    template_id: uuid.UUID,
    user: User,
) -> Template:
    """Раздел 19.2: чужой шаблон для `user` неотличим от несуществующего."""
    return await get_template_for_user(db_session, template_id, user=user)


async def _mcp_server_ids(db_session: AsyncSession, template_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = sa.select(TemplateMcpServer.mcp_server_id).where(
        TemplateMcpServer.template_id == template_id,
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def _to_response(db_session: AsyncSession, template: Template) -> TemplateResponse:
    return TemplateResponse(
        id=template.id,
        name=template.name,
        files=template.files,
        mcp_server_ids=await _mcp_server_ids(db_session, template.id),
        created_by=template.created_by,
    )


async def _replace_mcp_server_links(
    db_session: AsyncSession,
    *,
    template_id: uuid.UUID,
    mcp_server_ids: list[uuid.UUID],
) -> None:
    await db_session.execute(
        sa.delete(TemplateMcpServer).where(TemplateMcpServer.template_id == template_id),
    )
    for mcp_server_id in mcp_server_ids:
        db_session.add(
            TemplateMcpServer(template_id=template_id, mcp_server_id=mcp_server_id),
        )


@router.post("", response_model=TemplateResponse, status_code=201)
async def create_template(
    body: TemplateCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TemplateResponse:
    template = Template(
        id=uuid.uuid4(),
        name=body.name,
        files=body.files,
        created_by=current_user.id,
    )
    db_session.add(template)
    await db_session.flush()
    await _replace_mcp_server_links(
        db_session,
        template_id=template.id,
        mcp_server_ids=body.mcp_server_ids,
    )
    await db_session.commit()
    return await _to_response(db_session, template)


@router.get("", response_model=list[TemplateResponse])
async def list_templates(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TemplateResponse]:
    stmt = (
        sa.select(Template)
        .where(owner_filter(Template.created_by, current_user))
        .order_by(Template.name)
    )
    templates = list((await db_session.execute(stmt)).scalars().all())
    return [await _to_response(db_session, template) for template in templates]


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TemplateResponse:
    template = await _get_template_or_404(db_session, template_id, current_user)
    return await _to_response(db_session, template)


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TemplateResponse:
    template = await _get_template_or_404(db_session, template_id, current_user)
    if body.name is not None:
        template.name = body.name
    if body.files is not None:
        template.files = body.files
    if body.mcp_server_ids is not None:
        await _replace_mcp_server_links(
            db_session,
            template_id=template.id,
            mcp_server_ids=body.mcp_server_ids,
        )
    await db_session.commit()
    return await _to_response(db_session, template)


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    template = await _get_template_or_404(db_session, template_id, current_user)
    await db_session.delete(template)
    try:
        await db_session.commit()
    except sa.exc.IntegrityError as exc:
        await db_session.rollback()
        raise ConflictError(
            "Шаблон используется хотя бы одним репозиторием (default_template_id)",
        ) from exc
