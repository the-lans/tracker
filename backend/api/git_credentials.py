"""
Администрирование общих учётных данных Git. Секреты только на запись.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import httpx
import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from api.schemas import (
    CredentialCheckRequest,
    CredentialCheckResponse,
    CredentialInput,
    CredentialResponse,
)
from clients.gitlab import GitlabClient, project_path_from_git_url
from db.models.repositories import GitCredential, Repository
from db.models.users import User
from db.session import get_session
from services.crypto import encrypt
from services.errors import ConflictError, ExternalServiceError, ValidationError
from services.git_credentials import (
    HTTPS_TOKEN_KIND,
    gitlab_api_access,
    lock_credential,
    next_ssh_known_hosts,
    resolve_credential,
    validate_gitlab_api,
    validate_host,
    validate_secret,
    validate_username,
)
from services.git_ops import check_git_access
from services.integrity import commit_or_conflict
from services.ssh_known_hosts import known_hosts_fingerprints

router = APIRouter(prefix="/git-credentials", tags=["git-credentials"])
Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[User, Depends(require_admin)]
Current = Annotated[User, Depends(get_current_user)]


GITLAB_API_TIMEOUT_SECONDS = 15.0
GITLAB_API_OK = "ok"
GITLAB_API_DISABLED = "disabled"


def _response(row: GitCredential) -> CredentialResponse:
    return CredentialResponse(
        id=row.id,
        name=row.name,
        kind=row.kind,
        host=row.host,
        username=row.username,
        gitlab_api_enabled=row.gitlab_api_enabled,
        gitlab_api_url=row.gitlab_api_url,
        gitlab_api_token_set=row.gitlab_api_token_encrypted is not None,
        ssh_host_key_fingerprints=known_hosts_fingerprints(row.ssh_known_hosts),
    )


def _apply_gitlab_api(row: GitCredential, body: CredentialInput) -> None:
    """Токен API: `None` — без изменений, пустая строка — удалить."""
    if body.gitlab_api_token is not None:
        validate_secret(HTTPS_TOKEN_KIND, body.gitlab_api_token)
        row.gitlab_api_token_encrypted = (
            encrypt(body.gitlab_api_token) if body.gitlab_api_token else None
        )
    validate_gitlab_api(
        kind=body.kind,
        enabled=body.gitlab_api_enabled,
        has_token=row.gitlab_api_token_encrypted is not None,
    )
    row.gitlab_api_enabled = body.gitlab_api_enabled
    row.gitlab_api_url = body.gitlab_api_url.rstrip("/") if body.gitlab_api_url else None


@router.get("", response_model=list[CredentialResponse])
async def list_credentials(session: Session, _: Current) -> list[CredentialResponse]:
    rows = await session.scalars(sa.select(GitCredential).order_by(GitCredential.name))
    return [_response(row) for row in rows]


@router.post("", response_model=CredentialResponse, status_code=201)
async def create_credential(
    body: CredentialInput,
    session: Session,
    _: Admin,
) -> CredentialResponse:
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
    _apply_gitlab_api(row, body)
    row.ssh_known_hosts = next_ssh_known_hosts(
        kind=body.kind,
        stored=None,
        submitted=body.ssh_known_hosts,
        server_changed=False,
    )
    session.add(row)
    await session.commit()
    return _response(row)


@router.put("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: uuid.UUID,
    body: CredentialInput,
    session: Session,
    _: Admin,
) -> CredentialResponse:
    row = await lock_credential(session, credential_id)
    host = validate_host(body.host)
    server_changed = (row.kind, row.host) != (body.kind, host)
    if server_changed:
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
    _apply_gitlab_api(row, body)
    row.ssh_known_hosts = next_ssh_known_hosts(
        kind=body.kind,
        stored=row.ssh_known_hosts,
        submitted=body.ssh_known_hosts,
        server_changed=server_changed,
    )
    row.name, row.kind, row.host, row.username = body.name, body.kind, host, body.username
    await session.commit()
    return _response(row)


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


@router.post("/{credential_id}/check")
async def check_credential(
    credential_id: uuid.UUID,
    body: CredentialCheckRequest,
    session: Session,
    _: Admin,
) -> CredentialCheckResponse:
    credential = await resolve_credential(session, credential_id, body.git_url)
    # Блокировка учётных данных не держится на время сетевого запроса: ключ
    # хоста, полученный им, сохраняется своей транзакцией (раздел 19.3).
    await session.commit()
    await check_git_access(Repository(git_url=body.git_url, git_credential=credential))
    gitlab_api = await _check_gitlab_api(credential, body.git_url)
    if credential is not None:
        # Ключ сохранила своя транзакция `check_git_access` — перечитываем.
        await session.refresh(credential)
    return CredentialCheckResponse(
        read_access=True,
        gitlab_api=gitlab_api,
        ssh_host_key_fingerprints=known_hosts_fingerprints(
            credential.ssh_known_hosts if credential is not None else None,
        ),
    )


async def _check_gitlab_api(credential: GitCredential | None, git_url: str) -> str:
    """Итог проверки API: `ok`, `disabled` или причина отказа — Git-доступ она не отменяет."""
    access = gitlab_api_access(credential)
    if access is None:
        return GITLAB_API_DISABLED
    async with httpx.AsyncClient(timeout=GITLAB_API_TIMEOUT_SECONDS) as http_client:
        client = GitlabClient(base_url=access.base_url, token=access.token, http_client=http_client)
        try:
            await client.get_project(project_path_from_git_url(git_url))
        except ExternalServiceError as exc:
            return exc.message
    return GITLAB_API_OK
