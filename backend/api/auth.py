"""Вход через Google OAuth (раздел 19.1 ТЗ).

Frontend получает `id_token` от Google Identity Services (client-side flow)
и передаёт его сюда одним запросом — backend не участвует в OAuth-редиректе
самостоятельно, только проверяет подпись готового id_token.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import UserRole
from db.session import get_session
from services.auth import GoogleAuthLibraryVerifier, GoogleIdTokenVerifier, authenticate_or_register
from services.auth_tokens import issue_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleLoginRequest(BaseModel):
    id_token: str


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    role: UserRole


class LoginResponse(BaseModel):
    session_token: str
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
    db_session: Annotated[AsyncSession, Depends(get_session)],
    verifier: Annotated[GoogleIdTokenVerifier, Depends(get_google_verifier)],
) -> LoginResponse:
    identity = verifier.verify(body.id_token)
    user = await authenticate_or_register(db_session, identity=identity)
    session_token = issue_session_token(user.id)
    return LoginResponse(
        session_token=session_token,
        user=CurrentUserResponse(id=str(user.id), email=user.email, role=user.role),
    )
