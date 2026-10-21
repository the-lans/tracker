"""`api/profile.py` — профиль и SSH-ключ sshfs (раздел 15.1 ТЗ)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.factories import SAMPLE_ECDSA_KEY, SAMPLE_ED25519_FINGERPRINT, SAMPLE_ED25519_KEY

if TYPE_CHECKING:
    from httpx import AsyncClient

    from db.models.users import User


class TestSshKey:
    async def test_profile_without_key(
        self,
        authed_client: AsyncClient,
        current_user: User,
    ) -> None:
        response = await authed_client.get("/profile")

        assert response.status_code == 200
        assert response.json()["email"] == current_user.email
        assert response.json()["ssh_public_key"] is None
        assert response.json()["ssh_key_fingerprint"] is None

    async def test_set_replace_and_delete(self, authed_client: AsyncClient) -> None:
        first = await authed_client.put(
            "/profile/ssh-key",
            json={"public_key": f" {SAMPLE_ED25519_KEY}\n"},
        )
        replaced = await authed_client.put(
            "/profile/ssh-key",
            json={"public_key": SAMPLE_ECDSA_KEY},
        )
        deleted = await authed_client.delete("/profile/ssh-key")

        assert first.status_code == 200
        assert first.json()["ssh_public_key"] == SAMPLE_ED25519_KEY
        assert first.json()["ssh_key_fingerprint"] == SAMPLE_ED25519_FINGERPRINT
        assert replaced.json()["ssh_public_key"].startswith("ecdsa-sha2-nistp256 ")
        assert deleted.json()["ssh_public_key"] is None

    async def test_invalid_key_is_422(self, authed_client: AsyncClient) -> None:
        response = await authed_client.put("/profile/ssh-key", json={"public_key": "ssh-rsa xxx"})

        assert response.status_code == 422
