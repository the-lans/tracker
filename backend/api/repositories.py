"""CRUD `repositories` (раздел 3.1 ТЗ) — доступно любому авторизованному
пользователю (используется при настройке задачи, не относится к
административной части раздела 15.5)."""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import RepositoryCreateRequest, RepositoryResponse, RepositoryUpdateRequest
from db.models.repositories import Repository
from db.models.users import User
from db.session import get_session
from services.access import get_or_404, get_template_for_user
from services.crypto import encrypt
from services.integrity import (
    commit_or_conflict,
    ensure_repository_deletable,
    ensure_repository_renamable,
)
from services.repository_validation import validate_git_url, validate_repository_name

router = APIRouter(prefix="/repositories", tags=["repositories"])


async def _get_repository_or_404(db_session: AsyncSession, repository_id: uuid.UUID) -> Repository:
    return await get_or_404(
        db_session,
        Repository,
        repository_id,
        not_found=f"Репозиторий {repository_id} не найден",
    )


@router.post("", response_model=RepositoryResponse, status_code=201)
async def create_repository(
    body: RepositoryCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Repository:
    if body.default_template_id is not None:
        await get_template_for_user(db_session, body.default_template_id, user=current_user)
    repository = Repository(
        id=uuid.uuid4(),
        name=validate_repository_name(body.name),
        git_url=validate_git_url(body.git_url),
        default_template_id=body.default_template_id,
        deploy_key_encrypted=encrypt(body.deploy_key),
    )
    db_session.add(repository)
    await db_session.commit()
    return repository


@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[Repository]:
    stmt = sa.select(Repository).order_by(Repository.name)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{repository_id}", response_model=RepositoryResponse)
async def get_repository(
    repository_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> Repository:
    return await _get_repository_or_404(db_session, repository_id)


@router.patch("/{repository_id}", response_model=RepositoryResponse)
async def update_repository(
    repository_id: uuid.UUID,
    body: RepositoryUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Repository:
    repository = await _get_repository_or_404(db_session, repository_id)
    if body.name is not None and body.name != repository.name:
        await ensure_repository_renamable(db_session, repository_id)
        repository.name = validate_repository_name(body.name)
    if body.git_url is not None:
        repository.git_url = validate_git_url(body.git_url)
    if (
        "default_template_id" in body.model_fields_set
        and body.default_template_id != repository.default_template_id
    ):
        # Решение №16 плана: `user` выбирает шаблон по умолчанию только среди
        # своих; уже назначенный чужой шаблон сохраняется без проверки, а
        # явный `null` снимает шаблон.
        if body.default_template_id is not None:
            await get_template_for_user(db_session, body.default_template_id, user=current_user)
        repository.default_template_id = body.default_template_id
    if body.deploy_key is not None:
        repository.deploy_key_encrypted = encrypt(body.deploy_key)
    await db_session.commit()
    await db_session.refresh(repository)
    return repository


@router.delete("/{repository_id}", status_code=204)
async def delete_repository(
    repository_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Правило 9 CLAUDE.md/раздел 3.2: репозиторий, привязанный к любой
    задаче, удалить нельзя (см. `services/integrity.py`).

    Даже когда guard пропускает (все связанные задачи — в терминальном
    статусе), `task_repositories` — постоянная историческая запись (правило
    5 CLAUDE.md касается только рабочей директории на диске, не строки в
    БД) и не даёт `repository_id` без FK-ссылки: физическое удаление
    репозитория, когда-либо привязанного хотя бы к одной задаче, всё равно
    невозможно — это ловится здесь и превращается в понятный 409, а не в
    падение с сырой `IntegrityError`."""
    repository = await _get_repository_or_404(db_session, repository_id)
    await ensure_repository_deletable(db_session, repository_id)
    await db_session.delete(repository)
    await commit_or_conflict(
        db_session,
        message=(
            "Репозиторий привязан хотя бы к одной задаче (историческая запись "
            "task_repositories) — удаление невозможно"
        ),
    )
