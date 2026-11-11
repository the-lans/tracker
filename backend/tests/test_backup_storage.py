"""Хранилище копий в S3 (`services/backup/storage.py`, раздел 20.4 ТЗ)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from botocore.exceptions import EndpointConnectionError

from services.backup.settings import BackupConfig
from services.backup.storage import (
    S3Storage,
    StorageError,
    describe_error,
    make_client,
)
from tests.s3_support import FOLDER, FakeS3Client, client_error, fake_storage

if TYPE_CHECKING:
    from pathlib import Path

_SHA = "ab" * 32


@pytest.fixture
def client() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def storage(client: FakeS3Client) -> S3Storage:
    return fake_storage(client)


class TestFolder:
    async def test_created_once(self, client: FakeS3Client, storage: S3Storage) -> None:
        assert await storage.ensure_folder() is True
        assert await storage.ensure_folder() is False
        assert f"{FOLDER}/" in client.objects
        assert [call for call in client.calls if call[0] == "put"] == [("put", f"{FOLDER}/")]


class TestUpload:
    async def test_metadata_and_head(
        self,
        client: FakeS3Client,
        storage: S3Storage,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "copy.tar.gpg"
        source.write_bytes(b"encrypted")

        await storage.upload(source, "tracker-backup-1.tar.gpg", sha256=_SHA)
        stored = await storage.head("tracker-backup-1.tar.gpg")

        assert stored is not None
        assert (stored.key, stored.size, stored.sha256) == (
            f"{FOLDER}/tracker-backup-1.tar.gpg",
            len(b"encrypted"),
            _SHA,
        )

    async def test_head_missing(self, storage: S3Storage) -> None:
        assert await storage.head("nothing") is None


class TestListBackups:
    async def test_only_backups_sorted(self, client: FakeS3Client, storage: S3Storage) -> None:
        for name in (
            "tracker-backup-20261103T000000Z.tar.gpg",
            "tracker-backup-20261101T000000Z.tar.gpg",
            "tracker-backup-20261102T000000Z.tar.gpg",
            "RESTORE.md",
            "tracker-backup-partial.part",
        ):
            await storage.put_text(name, "x", content_type="text/plain")
        await fake_storage(client, folder="Other").put_text(
            "tracker-backup-20261104T000000Z.tar.gpg",
            "x",
            content_type="text/plain",
        )

        names = [storage.name_of(item) for item in await storage.list_backups()]

        assert names == [
            "tracker-backup-20261101T000000Z.tar.gpg",
            "tracker-backup-20261102T000000Z.tar.gpg",
            "tracker-backup-20261103T000000Z.tar.gpg",
        ]


class TestRetries:
    async def test_transient_then_success(self, client: FakeS3Client, storage: S3Storage) -> None:
        client.failures["put"] = [
            EndpointConnectionError(endpoint_url="https://s3.example.com"),
            client_error("InternalError", "PutObject"),
        ]

        await storage.put_text("RESTORE.md", "текст", content_type="text/markdown")

        assert [call[0] for call in client.calls] == ["put", "put", "put"]
        assert f"{FOLDER}/RESTORE.md" in client.objects

    @pytest.mark.parametrize("code", ["403", "AccessDenied", "NoSuchBucket", "InvalidAccessKeyId"])
    async def test_permanent_not_retried(
        self,
        client: FakeS3Client,
        storage: S3Storage,
        code: str,
    ) -> None:
        client.failures["put"] = [client_error(code, "PutObject")]

        with pytest.raises(StorageError):
            await storage.put_text("RESTORE.md", "текст", content_type="text/markdown")

        assert len(client.calls) == 1

    async def test_gives_up(self, client: FakeS3Client, storage: S3Storage) -> None:
        client.failures["put"] = [client_error("SlowDown", "PutObject") for _ in range(3)]

        with pytest.raises(StorageError, match="SlowDown"):
            await storage.put_text("RESTORE.md", "текст", content_type="text/markdown")

        assert len(client.calls) == 3


class TestProbe:
    async def test_cleans_up(self, client: FakeS3Client, storage: S3Storage) -> None:
        await storage.probe()

        assert [call[0] for call in client.calls] == ["put", "get", "delete"]
        assert client.objects == {}

    async def test_read_mismatch(self, client: FakeS3Client, storage: S3Storage) -> None:
        client.corrupt_reads = True

        with pytest.raises(StorageError, match="не то"):
            await storage.probe()


class TestDescribeError:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (client_error("SignatureDoesNotMatch"), "Доступ запрещён"),
            (client_error("NoSuchBucket"), "Бакет не найден"),
            (client_error("NoSuchKey"), "Объект не найден"),
            (client_error("InternalError"), "ошибкой InternalError"),
            (EndpointConnectionError(endpoint_url="https://s3.example.com"), "недоступно"),
        ],
    )
    def test_message(self, error: Exception, expected: str) -> None:
        assert expected in describe_error(error)


class TestClient:
    def test_checksums_only_when_required(self) -> None:
        """CRC-заголовки новых boto3 ломают S3-совместимые хранилища."""
        client = make_client(
            endpoint="https://s3.example.com",
            region="ru-1",
            access_key="AKEXAMPLE",
            secret_key="secret-example",
        )

        config: Any = client.meta.config
        assert config.request_checksum_calculation == "when_required"
        assert config.response_checksum_validation == "when_required"
        assert config.signature_version == "s3v4"
        assert client.meta.endpoint_url == "https://s3.example.com"

    def test_incomplete_config(self) -> None:
        config = BackupConfig(
            enabled=False,
            endpoint="https://s3.example.com",
            region="ru-1",
            bucket=None,
            access_key="AKEXAMPLE",
            secret_key="secret-example",
            folder="Tracker",
            retention_count=7,
            passphrase=None,
        )

        with pytest.raises(StorageError, match="не полностью"):
            S3Storage.from_config(config)
