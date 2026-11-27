"""Вход через Google OAuth (раздел 19.1 ТЗ).

Frontend получает `id_token` от Google Identity Services (client-side flow)
и передаёт его сюда одним запросом — backend не участвует в OAuth-редиректе
самостоятельно, только проверяет подпись готового id_token.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from db.models.enums import UserRole
from db.models.users import User
from db.session import get_session
from services.auth import (
    GoogleAuthLibraryVerifier,
    GoogleIdTokenVerifier,
    authenticate_or_register,
    revoke_user_sessions,
    verify_google_id_token,
)
from services.auth_tokens import issue_session_token
from services.browser_session import clear_session_cookie, set_session_cookie

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleLoginRequest(BaseModel):
    id_token: str


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    role: UserRole


class LoginResponse(BaseModel):
    user: CurrentUserResponse


@lru_cache(maxsize=1)
def _default_verifier() -> GoogleAuthLibraryVerifier:
    return GoogleAuthLibraryVerifier(client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"])


def get_google_verifier() -> GoogleIdTokenVerifier:
    """Раздел 19.1: реальная сетевая проверка — единственное неподменяемое
    место автотестами (см. `services/auth.py`); тесты API переопределяют
    эту FastAPI-зависимость фейком через `app.dependency_overrides`."""
    return _default_verifier()


@router.post("/google", response_model=LoginResponse)
async def login_with_google(
    body: GoogleLoginRequest,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    verifier: Annotated[GoogleIdTokenVerifier, Depends(get_google_verifier)],
) -> LoginResponse:
    identity = await verify_google_id_token(verifier, body.id_token)
    user = await authenticate_or_register(db_session, identity=identity)
    session_token = issue_session_token(user.id, session_version=user.session_version)
    set_session_cookie(response, session_token)
    return LoginResponse(
        user=CurrentUserResponse(id=str(user.id), email=user.email, role=user.role),
    )


@router.post("/logout-all", status_code=204)
async def logout_everywhere(
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """
    Раздел 19.1: токены пользователя на всех устройствах, включая этот, недействительны.
    """
    await revoke_user_sessions(db_session, current_user)

    clear_session_cookie(response)


@router.get("/me", response_model=CurrentUserResponse)
async def current_session(
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
) -> CurrentUserResponse:
    response.headers["Cache-Control"] = "no-store"
    return CurrentUserResponse(
        id=str(current_user.id), email=current_user.email, role=current_user.role
    )


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    clear_session_cookie(response)
