"""Административная часть — «Пользователи и доступ» (раздел 15.5, 19.1, 19.2 ТЗ)."""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_admin
from api.schemas import (
    AllowedEmailCreateRequest,
    AllowedEmailResponse,
    UserResponse,
    UserUpdateRequest,
)
from db.models.users import AllowedEmail, User
from db.session import get_session
from services.access import get_or_404
from services.errors import ConflictError
from services.users import ensure_allowed_email_deletable

router = APIRouter(tags=["admin-users"])


async def _get_user_or_404(db_session: AsyncSession, user_id: uuid.UUID) -> User:
    return await get_or_404(
        db_session,
        User,
        user_id,
        not_found=f"Пользователь {user_id} не найден",
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[User]:
    stmt = sa.select(User).order_by(User.email)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> User:
    return await _get_user_or_404(db_session, user_id)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> User:
    """Админ не может сам себя разжаловать/деактивировать — иначе можно
    случайно оставить систему без единого администратора."""
    user = await _get_user_or_404(db_session, user_id)
    demoting_self = user.id == admin.id and (
        (body.role is not None and body.role != user.role)
        or (body.is_active is not None and not body.is_active)
    )
    if demoting_self:
        raise ConflictError("Нельзя снять роль admin/деактивировать себя самого")

    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.os_username is not None:
        user.os_username = body.os_username
    try:
        await db_session.commit()
    except sa.exc.IntegrityError as exc:
        await db_session.rollback()
        raise ConflictError("Логин SFTP уже занят другим пользователем") from exc
    await db_session.refresh(user)
    return user


@router.get("/allowed-emails", response_model=list[AllowedEmailResponse])
async def list_allowed_emails(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[AllowedEmail]:
    stmt = sa.select(AllowedEmail).order_by(AllowedEmail.email)
    return list((await db_session.execute(stmt)).scalars().all())


@router.post("/allowed-emails", response_model=AllowedEmailResponse, status_code=201)
async def create_allowed_email(
    body: AllowedEmailCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_admin)],
) -> AllowedEmail:
    allowed_email = AllowedEmail(id=uuid.uuid4(), email=body.email, added_by=admin.id)
    db_session.add(allowed_email)
    await db_session.commit()
    return allowed_email


@router.delete("/allowed-emails/{allowed_email_id}", status_code=204)
async def delete_allowed_email(
    allowed_email_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    allowed_email = await get_or_404(
        db_session,
        AllowedEmail,
        allowed_email_id,
        not_found=f"Запись allowed_emails {allowed_email_id} не найдена",
    )
    await ensure_allowed_email_deletable(db_session, allowed_email)
    await db_session.delete(allowed_email)
    await db_session.commit()
