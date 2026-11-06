"""
Администрирование общих учётных данных Git. Секреты только на запись.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from db.models.repositories import GitCredential, Repository
from db.models.users import User
from db.session import get_session
from services.crypto import encrypt
from services.errors import ConflictError, ValidationError
from services.git_credentials import (
    lock_credential,
    resolve_credential,
    validate_host,
    validate_secret,
    validate_username,
)
from services.git_ops import check_git_access
from services.integrity import commit_or_conflict

router = APIRouter(prefix="/git-credentials", tags=["git-credentials"])
Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[User, Depends(require_admin)]
Current = Annotated[User, Depends(get_current_user)]


MAX_NAME_LENGTH = 200
MAX_HOST_LENGTH = 253
MAX_SECRET_LENGTH = 65536
MAX_GIT_URL_LENGTH = 2048
DEFAULT_HTTPS_USERNAME = "oauth2"


class CredentialInput(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    kind: Literal["https_token", "ssh_key"]
    host: str = Field(min_length=1, max_length=MAX_HOST_LENGTH)
    username: str = Field(default=DEFAULT_HTTPS_USERNAME, min_length=1, max_length=MAX_NAME_LENGTH)
    secret: str | None = Field(default=None, max_length=MAX_SECRET_LENGTH)


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    kind: str
    host: str
    username: str


@router.get("", response_model=list[CredentialResponse])
async def list_credentials(session: Session, _: Current) -> list[GitCredential]:
    return list(await session.scalars(sa.select(GitCredential).order_by(GitCredential.name)))


@router.post("", response_model=CredentialResponse, status_code=201)
async def create_credential(body: CredentialInput, session: Session, _: Admin) -> GitCredential:
    if not body.secret:
        raise ValidationError("Укажите токен или приватный SSH-ключ")
    validate_secret(body.kind, body.secret)
    validate_username(body.username)
    row = GitCredential(
        id=uuid.uuid4(),
        name=body.name,
        kind=body.kind,
        host=validate_host(body.host),
        username=body.username,
        secret_encrypted=encrypt(body.secret),
    )
    session.add(row)
    await session.commit()
    return row


@router.put("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: uuid.UUID,
    body: CredentialInput,
    session: Session,
    _: Admin,
) -> GitCredential:
    row = await lock_credential(session, credential_id)
    host = validate_host(body.host)
    if (row.kind, row.host) != (body.kind, host):
        if await session.scalar(
            sa.select(Repository.id)
            .where(
                Repository.git_credential_id == row.id,
            )
            .limit(1)
        ):
            raise ConflictError("Тип и хост используемого доступа менять нельзя")
    if row.kind != body.kind and not body.secret:
        raise ValidationError("При смене типа укажите новый секрет")
    if body.secret:
        validate_secret(body.kind, body.secret)
        row.secret_encrypted = encrypt(body.secret)
    validate_username(body.username)
    row.name, row.kind, row.host, row.username = body.name, body.kind, host, body.username
    await session.commit()
    return row


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(credential_id: uuid.UUID, session: Session, _: Admin) -> None:
    row = await lock_credential(session, credential_id)
    if await session.scalar(
        sa.select(Repository.id)
        .where(
            Repository.git_credential_id == row.id,
        )
        .limit(1)
    ):
        raise ConflictError("Учётные данные используются репозиторием")
    await session.delete(row)
    await commit_or_conflict(session, message="Учётные данные используются репозиторием")


class CredentialCheckRequest(BaseModel):
    git_url: str = Field(min_length=1, max_length=MAX_GIT_URL_LENGTH)


@router.post("/{credential_id}/check")
async def check_credential(
    credential_id: uuid.UUID,
    body: CredentialCheckRequest,
    session: Session,
    _: Admin,
) -> dict[str, bool]:
    credential = await resolve_credential(session, credential_id, body.git_url)
    await check_git_access(Repository(git_url=body.git_url, git_credential=credential))
    return {"read_access": True}
