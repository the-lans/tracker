"""`api/users.py` — раздел 15.5, 19.1, 19.2 ТЗ."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import UserRole
from db.models.users import AllowedEmail, User
from tests.factories import SAMPLE_ED25519_FINGERPRINT, SAMPLE_ED25519_KEY

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


async def test_admin_can_promote_another_user(
    admin_client: AsyncClient,
    current_user: User,
) -> None:
    response = await admin_client.patch(
        f"/users/{current_user.id}",
        json={"role": UserRole.ADMIN.value},
    )

    assert response.status_code == 200
    assert response.json()["role"] == UserRole.ADMIN.value


async def test_admin_cannot_demote_self(admin_client: AsyncClient, admin_user: User) -> None:
    response = await admin_client.patch(
        f"/users/{admin_user.id}",
        json={"role": UserRole.USER.value},
    )

    assert response.status_code == 409


async def test_admin_cannot_deactivate_self(admin_client: AsyncClient, admin_user: User) -> None:
    response = await admin_client.patch(
        f"/users/{admin_user.id}",
        json={"is_active": False},
    )

    assert response.status_code == 409


async def test_non_admin_cannot_list_users(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/users")

    assert response.status_code == 403


async def test_create_and_delete_allowed_email(admin_client: AsyncClient) -> None:
    create_response = await admin_client.post(
        "/allowed-emails",
        json={"email": "newcomer@example.com"},
    )
    assert create_response.status_code == 201
    allowed_email_id = create_response.json()["id"]

    delete_response = await admin_client.delete(f"/allowed-emails/{allowed_email_id}")

    assert delete_response.status_code == 204


class TestLastAdminEmail:
    async def test_cannot_delete(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        await db_session.execute(
            sa.update(User)
            .where(User.role == UserRole.ADMIN, User.id != admin_user.id)
            .values(is_active=False),
        )
        allowed_email = AllowedEmail(email=admin_user.email)
        db_session.add(allowed_email)
        await db_session.flush()

        response = await admin_client.delete(f"/allowed-emails/{allowed_email.id}")

        assert response.status_code == 409


class TestSshKeyInAdminList:
    async def test_key_and_fingerprint_visible(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        user = User(
            email=f"{uuid.uuid4()}@example.com",
            role=UserRole.USER,
            ssh_public_key=SAMPLE_ED25519_KEY,
        )
        db_session.add(user)
        await db_session.flush()

        response = await admin_client.get(f"/users/{user.id}")

        assert response.status_code == 200
        assert response.json()["ssh_public_key"] == SAMPLE_ED25519_KEY
        assert response.json()["ssh_key_fingerprint"] == SAMPLE_ED25519_FINGERPRINT
