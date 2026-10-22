"""`api/profile.py` — профиль, SSH-ключ и подключение к SFTP-шлюзу (раздел 15.1 ТЗ)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from services.sftp_connection import HOST_KEY_FILENAME
from tests.factories import SAMPLE_ECDSA_KEY, SAMPLE_ED25519_FINGERPRINT, SAMPLE_ED25519_KEY

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

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

    async def test_new_key_resets_last_use(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        """Раздел 16.2: давность использования считается заново для нового ключа."""
        current_user.ssh_public_key = SAMPLE_ED25519_KEY
        current_user.ssh_key_last_used_at = datetime(2026, 1, 1, tzinfo=UTC)
        await db_session.flush()

        body = {"public_key": SAMPLE_ECDSA_KEY}

        response = await authed_client.put("/profile/ssh-key", json=body)

        assert response.json()["ssh_key_last_used_at"] is None


class TestSftpConnection:
    async def test_with_host_key(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SFTP_HOST_KEYS_DIR", str(tmp_path))
        monkeypatch.setenv("DOMAIN", "tracker.example.com")
        monkeypatch.setenv("SFTP_PORT", "2222")
        (tmp_path / f"{HOST_KEY_FILENAME}.pub").write_text(SAMPLE_ED25519_KEY)
        current_user.os_username = "dev"
        await db_session.flush()

        response = await authed_client.get("/profile/sftp")

        assert response.json() == {
            "host": "tracker.example.com",
            "port": 2222,
            "username": "dev",
            "host_key_fingerprint": SAMPLE_ED25519_FINGERPRINT,
        }

    async def test_gateway_not_started(
        self,
        authed_client: AsyncClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SFTP_HOST_KEYS_DIR", str(tmp_path))

        response = await authed_client.get("/profile/sftp")

        assert response.json()["host_key_fingerprint"] is None
        assert response.json()["username"] is None
