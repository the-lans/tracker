"""CRUD `env_variables` (раздел 3.1, 5, 19.4 ТЗ) — административная часть
(раздел 15.5, "Системные настройки"): значения хранятся зашифрованными и
скрыты в UI по умолчанию (правило 8 CLAUDE.md) — обычный ответ никогда не
включает расшифрованное значение, для этого отдельный эндпоинт `.../reveal`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import require_admin
from api.schemas import (
    EnvVariableCreateRequest,
    EnvVariableResponse,
    EnvVariableRevealResponse,
    EnvVariableUpdateRequest,
)
from db.models.enums import EnvVariableScope
from db.models.env_vars import EnvVariable
from db.models.users import User
from db.session import get_session
from services.crypto import decrypt, encrypt
from services.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/env-variables", tags=["env-variables"])


def _validate_scope(*, scope: EnvVariableScope, repository_id: uuid.UUID | None) -> None:
    """Раздел 3.1: `repository_id` заполнено ровно при `scope = repository`
    (см. `ck_env_variables_scope_matches_repository_id` — тот же инвариант,
    проверенный здесь заранее ради понятного сообщения об ошибке до похода
    в БД)."""
    if scope is EnvVariableScope.GLOBAL and repository_id is not None:
        raise ValidationError("scope=global не допускает repository_id")
    if scope is EnvVariableScope.REPOSITORY and repository_id is None:
        raise ValidationError("scope=repository требует repository_id")


async def _get_env_variable_or_404(
    db_session: AsyncSession,
    env_variable_id: uuid.UUID,
) -> EnvVariable:
    env_variable = await db_session.get(EnvVariable, env_variable_id)
    if env_variable is None:
        raise NotFoundError(f"Переменная окружения {env_variable_id} не найдена")
    return env_variable


@router.post("", response_model=EnvVariableResponse, status_code=201)
async def create_env_variable(
    body: EnvVariableCreateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> EnvVariable:
    _validate_scope(scope=body.scope, repository_id=body.repository_id)
    env_variable = EnvVariable(
        id=uuid.uuid4(),
        key=body.key,
        value_encrypted=encrypt(body.value),
        is_secret=body.is_secret,
        scope=body.scope,
        repository_id=body.repository_id,
    )
    db_session.add(env_variable)
    await db_session.commit()
    return env_variable


@router.get("", response_model=list[EnvVariableResponse])
async def list_env_variables(
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> list[EnvVariable]:
    stmt = sa.select(EnvVariable).order_by(EnvVariable.key)
    return list((await db_session.execute(stmt)).scalars().all())


@router.get("/{env_variable_id}", response_model=EnvVariableResponse)
async def get_env_variable(
    env_variable_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> EnvVariable:
    return await _get_env_variable_or_404(db_session, env_variable_id)


@router.get("/{env_variable_id}/reveal", response_model=EnvVariableRevealResponse)
async def reveal_env_variable(
    env_variable_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> EnvVariableRevealResponse:
    env_variable = await _get_env_variable_or_404(db_session, env_variable_id)
    return EnvVariableRevealResponse(value=decrypt(env_variable.value_encrypted))


@router.patch("/{env_variable_id}", response_model=EnvVariableResponse)
async def update_env_variable(
    env_variable_id: uuid.UUID,
    body: EnvVariableUpdateRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> EnvVariable:
    env_variable = await _get_env_variable_or_404(db_session, env_variable_id)
    if body.value is not None:
        env_variable.value_encrypted = encrypt(body.value)
    if body.is_secret is not None:
        env_variable.is_secret = body.is_secret
    await db_session.commit()
    await db_session.refresh(env_variable)
    return env_variable


@router.delete("/{env_variable_id}", status_code=204)
async def delete_env_variable(
    env_variable_id: uuid.UUID,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    env_variable = await _get_env_variable_or_404(db_session, env_variable_id)
    await db_session.delete(env_variable)
    await db_session.commit()
