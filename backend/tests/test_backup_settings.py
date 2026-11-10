"""Настройки бэкапа в S3 (`services/backup/settings.py`, разделы 15.5, 20.4 ТЗ)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from db.models.backups import BackupRun
from db.models.enums import BackupRunKind, BackupRunStatus
from services.backup import storage as backup_storage
from services.backup.settings import (
    BackupSettingsUpdate,
    load_backup_config,
    update_backup_settings,
)
from services.crypto import decrypt
from services.errors import ValidationError
from services.system_settings import get_system_settings
from tests.s3_support import FakeS3Client, client_error, fake_storage

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

_SECRET = "s3-secret-example"
_PASSPHRASE = "correct horse battery staple"
_UPDATE = BackupSettingsUpdate(
    enabled=True,
    endpoint="https://s3.example.com/",
    region="ru-1",
    bucket="tracker-backups",
    access_key="AKEXAMPLE",
    secret_key=_SECRET,
    folder="/Tracker/prod/",
    retention_count=7,
    passphrase=_PASSPHRASE,
)
_BODY: dict[str, Any] = {
    "enabled": True,
    "endpoint": "https://s3.example.com",
    "region": "ru-1",
    "bucket": "tracker-backups",
    "access_key": "AKEXAMPLE",
    "secret_key": _SECRET,
    "folder": "Tracker",
    "retention_count": 7,
    "passphrase": _PASSPHRASE,
}


def _with(**changes: Any) -> BackupSettingsUpdate:
    return replace(_UPDATE, **changes)


class TestUpdate:
    async def test_normalized_and_encrypted(self, db_session: AsyncSession) -> None:
        settings = await update_backup_settings(db_session, update=_UPDATE)

        assert (settings.backup_s3_endpoint, settings.backup_s3_folder) == (
            "https://s3.example.com",
            "Tracker/prod",
        )
        assert settings.backup_s3_secret_key_encrypted != _SECRET
        assert decrypt(settings.backup_s3_secret_key_encrypted or "") == _SECRET
        config = await load_backup_config(db_session)
        assert (config.enabled, config.is_complete, config.passphrase) == (True, True, _PASSPHRASE)

    async def test_empty_secrets_keep_saved(self, db_session: AsyncSession) -> None:
        await update_backup_settings(db_session, update=_UPDATE)

        await update_backup_settings(
            db_session,
            update=replace(_UPDATE, secret_key="", passphrase=None, retention_count=3),
        )

        config = await load_backup_config(db_session)
        assert (config.secret_key, config.passphrase, config.retention_count) == (
            _SECRET,
            _PASSPHRASE,
            3,
        )

    @pytest.mark.parametrize(
        "missing",
        ["endpoint", "region", "bucket", "access_key", "secret_key", "passphrase"],
    )
    async def test_enable_requires_all(self, db_session: AsyncSession, missing: str) -> None:
        with pytest.raises(ValidationError, match="Чтобы включить"):
            await update_backup_settings(db_session, update=_with(**{missing: None}))

        assert (await get_system_settings(db_session)).backup_enabled is False

    async def test_disabled_may_be_incomplete(self, db_session: AsyncSession) -> None:
        settings = await update_backup_settings(
            db_session,
            update=replace(_UPDATE, enabled=False, bucket=None, passphrase=None),
        )

        assert settings.backup_enabled is False

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("endpoint", "http://s3.example.com"),
            ("endpoint", "https://s3.example.com/bucket"),
            ("endpoint", "https://user:pass@s3.example.com"),
            ("region", "RU 1"),
            ("bucket", "Tracker_Backups"),
            ("bucket", "ab"),
            ("access_key", "AK EXAMPLE"),
            ("secret_key", "with space"),
            ("folder", "../etc"),
            ("folder", "Tracker//prod"),
            ("folder", "Трекер"),
            ("folder", ""),
            ("passphrase", "short"),
            ("passphrase", "long enough\nsecond line"),
        ],
    )
    async def test_rejects(self, db_session: AsyncSession, field: str, value: str) -> None:
        with pytest.raises(ValidationError):
            await update_backup_settings(db_session, update=_with(**{field: value}))


class TestApi:
    async def test_secrets_not_returned(self, admin_client: AsyncClient) -> None:
        response = await admin_client.put("/system-settings/backup", json=_BODY)

        assert response.status_code == 200, response.text
        body = response.json()
        assert _SECRET not in response.text and _PASSPHRASE not in response.text
        assert (body["secret_key_set"], body["passphrase_set"]) == (True, True)
        assert "secret_key" not in body and "passphrase" not in body
        assert (await admin_client.get("/system-settings/backup")).json() == body

    async def test_defaults(self, admin_client: AsyncClient) -> None:
        body = (await admin_client.get("/system-settings/backup")).json()

        assert body == {
            "enabled": False,
            "endpoint": None,
            "region": None,
            "bucket": None,
            "access_key": None,
            "secret_key_set": False,
            "folder": "Tracker",
            "retention_count": 7,
            "passphrase_set": False,
            "last_backup": None,
            "last_verify": None,
        }

    async def test_last_runs(self, admin_client: AsyncClient, db_session: AsyncSession) -> None:
        db_session.add_all(
            [
                BackupRun(
                    kind=BackupRunKind.BACKUP,
                    status=BackupRunStatus.WARNING,
                    object_key="Tracker/tracker-backup-1.tar.gpg",
                    size_bytes=2048,
                    skipped_files=[{"component": "c", "path": "p", "reason": "r"}],
                ),
                BackupRun(
                    kind=BackupRunKind.VERIFY,
                    status=BackupRunStatus.FAILED,
                    error_message="Число строк не совпадает",
                ),
            ],
        )
        await db_session.commit()

        body = (await admin_client.get("/system-settings/backup")).json()

        assert (body["last_backup"]["status"], body["last_backup"]["size_bytes"]) == (
            "warning",
            2048,
        )
        assert body["last_backup"]["skipped_files"][0]["path"] == "p"
        assert body["last_verify"]["error_message"] == "Число строк не совпадает"

    @pytest.mark.parametrize(
        ("field", "value"),
        [("retention_count", 0), ("retention_count", 366), ("enabled", None)],
    )
    async def test_schema_rejects(self, admin_client: AsyncClient, field: str, value: Any) -> None:
        response = await admin_client.put("/system-settings/backup", json={**_BODY, field: value})

        assert response.status_code == 422

    async def test_enable_incomplete(self, admin_client: AsyncClient) -> None:
        response = await admin_client.put(
            "/system-settings/backup",
            json={**_BODY, "passphrase": None},
        )

        assert response.status_code == 422
        assert "Чтобы включить" in response.text

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/system-settings/backup"),
            ("put", "/system-settings/backup"),
            ("post", "/system-settings/backup/check"),
        ],
    )
    async def test_admin_only(self, authed_client: AsyncClient, method: str, path: str) -> None:
        response = await authed_client.request(method, path, json=_BODY)

        assert response.status_code == 403


class TestConnectionCheck:
    @pytest.fixture
    def client(self, monkeypatch: pytest.MonkeyPatch) -> FakeS3Client:
        client = FakeS3Client()
        monkeypatch.setattr(
            backup_storage.S3Storage,
            "from_config",
            classmethod(lambda cls, config, retry_delays=(): fake_storage(client)),
        )
        return client

    async def test_ok_creates_folder(self, admin_client: AsyncClient, client: FakeS3Client) -> None:
        await admin_client.put("/system-settings/backup", json=_BODY)

        response = await admin_client.post("/system-settings/backup/check")

        assert response.json() == {
            "ok": True,
            "message": "Подключение работает: запись и чтение прошли, папка Tracker создана",
        }
        assert "Tracker-test/" in client.objects

    async def test_failure_without_secrets(
        self,
        admin_client: AsyncClient,
        client: FakeS3Client,
    ) -> None:
        await admin_client.put("/system-settings/backup", json=_BODY)
        client.failures["put"] = [client_error("SignatureDoesNotMatch", "PutObject")]

        response = await admin_client.post("/system-settings/backup/check")

        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "Доступ запрещён" in response.json()["message"]
        assert _SECRET not in response.text

    async def test_not_configured(self, admin_client: AsyncClient) -> None:
        response = await admin_client.post("/system-settings/backup/check")

        assert response.json() == {"ok": False, "message": "Настройки S3 заполнены не полностью"}
