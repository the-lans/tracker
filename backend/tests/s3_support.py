"""
Фейковый клиент S3 для тестов бэкапа (`services/backup/storage.py`): объекты
в памяти, те же вызовы boto3, что делает `S3Storage`, и сбои по заказу.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from botocore.exceptions import ClientError

from services.backup.storage import S3Storage

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

BUCKET = "tracker-test-bucket"
FOLDER = "Tracker-test"


def client_error(code: str, operation: str = "HeadObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


@dataclass
class StoredBlob:
    body: bytes
    metadata: dict[str, str] = field(default_factory=dict)
    content_type: str | None = None
    last_modified: datetime = field(default_factory=lambda: datetime.now(UTC))


class _Paginator:
    def __init__(self, client: FakeS3Client) -> None:
        self._client = client

    def paginate(self, *, Bucket: str, Prefix: str) -> Iterator[dict[str, Any]]:  # noqa: N803
        self._client.record("list", Prefix)
        keys = sorted(key for key in self._client.objects if key.startswith(Prefix))
        yield {
            "Contents": [
                {
                    "Key": key,
                    "Size": len(self._client.objects[key].body),
                    "LastModified": self._client.objects[key].last_modified,
                }
                for key in keys
            ],
        }


class FakeS3Client:
    """Подмножество boto3 S3-клиента, которым пользуется `S3Storage`."""

    def __init__(self) -> None:
        self.objects: dict[str, StoredBlob] = {}
        self.calls: list[tuple[str, str]] = []
        # Операция → исключения, которые бросят следующие вызовы по очереди.
        self.failures: dict[str, list[Exception]] = {}
        # Подменить тело при чтении (проверка «записали не то»).
        self.corrupt_reads = False

    def record(self, operation: str, key: str) -> None:
        self.calls.append((operation, key))
        pending = self.failures.get(operation)
        if pending:
            raise pending.pop(0)

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.record("head", Key)
        blob = self.objects.get(Key)
        if blob is None:
            raise client_error("404")
        return {
            "ContentLength": len(blob.body),
            "Metadata": dict(blob.metadata),
            "LastModified": blob.last_modified,
        }

    def put_object(
        self,
        *,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Body: bytes,  # noqa: N803
        ContentType: str | None = None,  # noqa: N803
    ) -> dict[str, Any]:
        self.record("put", Key)
        self.objects[Key] = StoredBlob(body=Body, content_type=ContentType)
        return {}

    def upload_file(
        self,
        Filename: str,  # noqa: N803
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        ExtraArgs: dict[str, Any] | None = None,  # noqa: N803
        Config: object = None,  # noqa: N803
    ) -> None:
        self.record("upload", Key)
        metadata = (ExtraArgs or {}).get("Metadata", {})
        self.objects[Key] = StoredBlob(body=Path(Filename).read_bytes(), metadata=dict(metadata))

    def download_file(
        self,
        Bucket: str,  # noqa: N803
        Key: str,  # noqa: N803
        Filename: str,  # noqa: N803
        Config: object = None,  # noqa: N803
    ) -> None:
        self.record("download", Key)
        blob = self.objects.get(Key)
        if blob is None:
            raise client_error("404", "GetObject")
        with Path(Filename).open("wb") as target:
            shutil.copyfileobj(BytesIO(blob.body), target)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.record("get", Key)
        blob = self.objects.get(Key)
        if blob is None:
            raise client_error("NoSuchKey", "GetObject")
        body = b"corrupted" if self.corrupt_reads else blob.body
        return {"Body": BytesIO(body)}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.record("delete", Key)
        self.objects.pop(Key, None)
        return {}

    def get_paginator(self, operation: str) -> _Paginator:
        assert operation == "list_objects_v2"
        return _Paginator(self)

    def backup_keys(self) -> list[str]:
        return sorted(key for key in self.objects if key.endswith(".tar.gpg"))


def fake_storage(client: FakeS3Client, *, folder: str = FOLDER) -> S3Storage:
    return S3Storage(
        cast("S3Client", client),
        bucket=BUCKET,
        folder=folder,
        retry_delays=(0, 0),
    )
