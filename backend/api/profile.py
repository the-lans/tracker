"""Профиль пользователя (раздел 15.1 ТЗ): собственные данные, SSH-ключ и подключение к SFTP."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import SftpConnectionResponse, SshKeyUpdateRequest, UserResponse
from db.models.users import User
from db.session import get_session
from services.sftp_connection import SftpConnection, sftp_connection_for
from services.users import clear_ssh_public_key, set_ssh_public_key

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=UserResponse)
async def get_profile(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@router.get("/sftp", response_model=SftpConnectionResponse)
async def get_sftp_connection(
    current_user: Annotated[User, Depends(get_current_user)],
) -> SftpConnection:
    """Раздел 15.1: хост, порт, логин и отпечаток ключа сервера для инструкции подключения."""
    return sftp_connection_for(current_user)


@router.put("/ssh-key", response_model=UserResponse)
async def update_ssh_key(
    body: SshKeyUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Один ключ на пользователя: новый ключ заменяет прежний (решение №16 плана)."""
    return await set_ssh_public_key(db_session, user=current_user, public_key=body.public_key)


@router.delete("/ssh-key", response_model=UserResponse)
async def delete_ssh_key(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return await clear_ssh_public_key(db_session, user=current_user)
