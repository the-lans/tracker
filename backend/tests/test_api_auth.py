"""`POST /auth/google` (раздел 19.1 ТЗ).

Реальная сетевая проверка Google id_token (`GoogleAuthLibraryVerifier`)
намеренно не тестируется (раздел "local-first" — см. `services/auth.py`);
здесь эндпоинт целиком, кроме самой верификации, подменённой фейком через
`app.dependency_overrides[get_google_verifier]`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from google.auth.exceptions import MalformedError, TransportError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_google_verifier
from db.models.enums import UserRole
from db.models.users import AllowedEmail, User
from services.auth import GoogleIdentity

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _reset_verifier() -> Iterator[None]:
    """Подменённый верификатор Google не переходит в следующие тесты."""
    yield
    from main import app

    app.dependency_overrides.pop(get_google_verifier, None)


class _FakeVerifier:
    def __init__(self, identity: GoogleIdentity) -> None:
        self._identity = identity

    def verify(self, id_token_jwt: str) -> GoogleIdentity:  # noqa: ARG002
        return self._identity


def _override_verifier(identity: GoogleIdentity) -> None:
    from main import app

    app.dependency_overrides[get_google_verifier] = lambda: _FakeVerifier(identity)


async def test_login_registers_first_allowed_user_as_admin(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"{uuid.uuid4()}@example.com"
    db_session.add(AllowedEmail(email=email))
    await db_session.flush()
    _override_verifier(GoogleIdentity(email=email, email_verified=True))

    response = await api_client.post("/auth/google", json={"id_token": "fake-jwt"})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == email
    assert body["user"]["role"] == UserRole.ADMIN.value
    assert body["session_token"]


async def test_login_rejects_email_outside_allowlist(api_client: AsyncClient) -> None:
    email = f"{uuid.uuid4()}@example.com"
    _override_verifier(GoogleIdentity(email=email, email_verified=True))

    response = await api_client.post("/auth/google", json={"id_token": "fake-jwt"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_login_rejects_unverified_email(api_client: AsyncClient) -> None:
    _override_verifier(GoogleIdentity(email="unverified@example.com", email_verified=False))

    response = await api_client.post("/auth/google", json={"id_token": "fake-jwt"})

    assert response.status_code == 422


async def test_login_returns_working_session_token_for_existing_user(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    email = f"{uuid.uuid4()}@example.com"
    existing = User(id=uuid.uuid4(), email=email, role=UserRole.USER, is_active=True)
    db_session.add(existing)
    await db_session.flush()
    _override_verifier(GoogleIdentity(email=email, email_verified=True))

    response = await api_client.post("/auth/google", json={"id_token": "fake-jwt"})

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(existing.id)


class _FailingVerifier:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def verify(self, id_token_jwt: str) -> GoogleIdentity:  # noqa: ARG002
        raise self._error


class TestRejectedToken:
    """Раздел 19.1: плохой токен Google — 401, а не «внутренняя ошибка»."""

    @pytest.mark.parametrize(
        ("error", "status_code"),
        [
            (MalformedError("Certificate for key id abc not found."), 401),
            (ValueError("Token expired"), 401),
            (TransportError("connection refused"), 502),
        ],
        ids=["malformed", "expired", "google_unavailable"],
    )
    async def test_status(
        self,
        api_client: AsyncClient,
        error: Exception,
        status_code: int,
    ) -> None:
        from main import app

        app.dependency_overrides[get_google_verifier] = lambda: _FailingVerifier(error)

        response = await api_client.post("/auth/google", json={"id_token": "bad"})

        assert response.status_code == status_code
