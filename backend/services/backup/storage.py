"""
S3-совместимое хранилище копий (раздел 20.4 ТЗ).

boto3 синхронный — вызовы уходят в поток (`asyncio.to_thread`). Временные
сбои (сеть, 5xx, троттлинг) повторяет сам botocore (режим `standard`), а
операция целиком повторяется ещё несколько раз с паузами: загрузка в
десятки минут не должна падать из-за одного обрыва. Отказ в доступе и
отсутствие объекта не повторяются — это не пройдёт само.

Новые CRC-заголовки контрольных сумм boto3 ломают часть S3-совместимых
хранилищ — они включаются только там, где их требует сам API.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app_logging.config import get_logger

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

    from services.backup.settings import BackupConfig

logger = get_logger("backup_storage")

T = TypeVar("T")

BACKUP_PREFIX = "tracker-backup-"
BACKUP_SUFFIX = ".tar.gpg"
SHA256_METADATA = "sha256"
PROBE_OBJECT = ".tracker-probe"
PROBE_BODY = b"tracker backup probe"
DEFAULT_RETRY_DELAYS_SECONDS: tuple[float, ...] = (5, 30, 120)
_BOTOCORE_MAX_ATTEMPTS = 5
_CONNECT_TIMEOUT_SECONDS = 15
_READ_TIMEOUT_SECONDS = 120
_MEBIBYTE = 1024 * 1024
_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=64 * _MEBIBYTE,
    multipart_chunksize=64 * _MEBIBYTE,
    max_concurrency=4,
)
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
# Повтор не поможет: ключи, права, бакет или сам запрос неверны.
_PERMANENT_CODES = frozenset(
    {
        "400",
        "403",
        "AccessDenied",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "NoSuchBucket",
        "InvalidBucketName",
        "AuthorizationHeaderMalformed",
        "InvalidRequest",
    }
    | _NOT_FOUND_CODES,
)
_ACCESS_CODES = frozenset(
    {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"},
)


class StorageError(Exception):
    """Сбой хранилища; текст понятен администратору и не содержит секретов."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    sha256: str | None
    last_modified: datetime | None


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def describe_error(exc: Exception) -> str:
    """Причина сбоя для UI и `backup_runs` — без ключей и подписей запроса."""
    if isinstance(exc, ClientError):
        code = _error_code(exc)
        if code in _ACCESS_CODES:
            return "Доступ запрещён: проверьте ключ доступа, секретный ключ и права на бакет"
        if code == "NoSuchBucket":
            return "Бакет не найден"
        if code in _NOT_FOUND_CODES:
            return "Объект не найден"
        return f"Хранилище ответило ошибкой {code or 'без кода'}"
    if isinstance(exc, BotoCoreError):
        return f"Хранилище недоступно: {type(exc).__name__}"
    return str(exc)


def _is_permanent(exc: Exception) -> bool:
    return isinstance(exc, ClientError) and _error_code(exc) in _PERMANENT_CODES


def make_client(*, endpoint: str, region: str, access_key: str, secret_key: str) -> S3Client:
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": _BOTOCORE_MAX_ATTEMPTS, "mode": "standard"},
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            read_timeout=_READ_TIMEOUT_SECONDS,
        ),
    )


class S3Storage:
    """Копии трекера в папке бакета: `<папка>/tracker-backup-<UTC>.tar.gpg`."""

    def __init__(
        self,
        client: S3Client,
        *,
        bucket: str,
        folder: str,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._folder = folder
        self._retry_delays = tuple(retry_delays)

    @classmethod
    def from_config(
        cls,
        config: BackupConfig,
        *,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS,
    ) -> S3Storage:
        """Хранилище по настройкам; пароль шифрования для него не нужен."""
        if not (
            config.endpoint
            and config.region
            and config.bucket
            and config.access_key
            and config.secret_key
        ):
            raise StorageError("Настройки S3 заполнены не полностью")
        client = make_client(
            endpoint=config.endpoint,
            region=config.region,
            access_key=config.access_key,
            secret_key=config.secret_key,
        )
        return cls(client, bucket=config.bucket, folder=config.folder, retry_delays=retry_delays)

    def key(self, name: str) -> str:
        return f"{self._folder}/{name}"

    async def _call(self, operation: str, function: Callable[[], T]) -> T:
        attempts = len(self._retry_delays) + 1
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.to_thread(function)
            except (BotoCoreError, ClientError) as exc:
                if _is_permanent(exc) or attempt == attempts:
                    raise StorageError(describe_error(exc)) from exc
                delay = self._retry_delays[attempt - 1]
                logger.warning(
                    "backup_storage_retry",
                    operation=operation,
                    attempt=attempt,
                    delay_seconds=delay,
                    error=describe_error(exc),
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _head_raw(self, key: str) -> dict[str, Any] | None:
        def head() -> dict[str, Any] | None:
            try:
                return dict(self._client.head_object(Bucket=self._bucket, Key=key))
            except ClientError as exc:
                if _error_code(exc) in _NOT_FOUND_CODES:
                    return None
                raise

        return await self._call("head", head)

    async def ensure_folder(self) -> bool:
        """Создаёт маркер папки `<папка>/`, если его нет; `True` — создан сейчас."""
        marker = f"{self._folder}/"
        if await self._head_raw(marker) is not None:
            return False
        await self._call(
            "create_folder",
            lambda: self._client.put_object(Bucket=self._bucket, Key=marker, Body=b""),
        )
        logger.info("backup_storage_folder_created", folder=self._folder)
        return True

    async def upload(self, path: Path, name: str, *, sha256: str) -> None:
        await self._call(
            "upload",
            lambda: self._client.upload_file(
                str(path),
                self._bucket,
                self.key(name),
                ExtraArgs={"Metadata": {SHA256_METADATA: sha256}},
                Config=_TRANSFER_CONFIG,
            ),
        )

    async def put_text(self, name: str, text: str, *, content_type: str) -> None:
        body = text.encode()
        await self._call(
            "put_text",
            lambda: self._client.put_object(
                Bucket=self._bucket,
                Key=self.key(name),
                Body=body,
                ContentType=content_type,
            ),
        )

    async def head(self, name: str) -> StoredObject | None:
        response = await self._head_raw(self.key(name))
        if response is None:
            return None
        metadata = response.get("Metadata") or {}
        return StoredObject(
            key=self.key(name),
            size=int(response.get("ContentLength", 0)),
            sha256=metadata.get(SHA256_METADATA),
            last_modified=response.get("LastModified"),
        )

    async def download(self, name: str, path: Path) -> None:
        await self._call(
            "download",
            lambda: self._client.download_file(
                self._bucket,
                self.key(name),
                str(path),
                Config=_TRANSFER_CONFIG,
            ),
        )

    async def list_backups(self) -> list[StoredObject]:
        """Копии трекера в папке, от старой к новой: имя содержит время UTC."""
        prefix = self.key(BACKUP_PREFIX)

        def list_all() -> list[StoredObject]:
            paginator = self._client.get_paginator("list_objects_v2")
            found: list[StoredObject] = []
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = item.get("Key", "")
                    if key.endswith(BACKUP_SUFFIX):
                        found.append(
                            StoredObject(
                                key=key,
                                size=int(item.get("Size", 0)),
                                sha256=None,
                                last_modified=item.get("LastModified"),
                            ),
                        )
            return sorted(found, key=lambda stored: stored.key)

        return await self._call("list", list_all)

    def name_of(self, stored: StoredObject) -> str:
        return stored.key.removeprefix(f"{self._folder}/")

    async def delete(self, name: str) -> None:
        await self._call(
            "delete",
            lambda: self._client.delete_object(Bucket=self._bucket, Key=self.key(name)),
        )

    async def probe(self) -> None:
        """Запись, чтение и удаление пробного объекта — права на всё, что делает бэкап."""
        key = self.key(PROBE_OBJECT)
        await self._call(
            "probe_put",
            lambda: self._client.put_object(Bucket=self._bucket, Key=key, Body=PROBE_BODY),
        )
        body = await self._call(
            "probe_get",
            lambda: self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read(),
        )
        await self._call(
            "probe_delete",
            lambda: self._client.delete_object(Bucket=self._bucket, Key=key),
        )
        if body != PROBE_BODY:
            raise StorageError("Хранилище вернуло не то, что было записано")
