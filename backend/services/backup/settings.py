"""
Настройки резервного копирования в S3 (разделы 15.5, 20.4 ТЗ).

Секретный ключ S3 и пароль шифрования хранятся зашифрованными
(`services.crypto`) и наружу не отдаются; пустое значение при сохранении —
оставить прежнее. Включить бэкап можно только при полностью заполненных
настройках: иначе ежедневная задача молча ничего бы не делала.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app_logging.config import get_logger
from services.backup.storage import S3Storage, StorageError
from services.crypto import decrypt, encrypt
from services.errors import ValidationError
from services.system_settings import get_system_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.settings import SystemSettings

logger = get_logger("backup_settings")

MIN_PASSPHRASE_LENGTH = 12
MAX_PASSPHRASE_LENGTH = 1024
MAX_FOLDER_LENGTH = 200
MAX_ACCESS_KEY_LENGTH = 256
# Адрес хранилища без пути: ключи объектов строятся от корня бакета.
_ENDPOINT_PATTERN = re.compile(r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?")
_REGION_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
# Правила имён бакетов S3: 3–63 символа, строчные буквы, цифры, точка, дефис.
_BUCKET_PATTERN = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_FOLDER_SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
_ACCESS_KEY_PATTERN = re.compile(r"\S+")
_RELATIVE_SEGMENTS = frozenset({".", ".."})


@dataclass(frozen=True, slots=True)
class BackupConfig:
    """Расшифрованные настройки для бэкапа и проверки; секреты — только в памяти."""

    enabled: bool
    endpoint: str | None
    region: str | None
    bucket: str | None
    access_key: str | None
    secret_key: str | None
    folder: str
    retention_count: int
    passphrase: str | None

    @property
    def is_complete(self) -> bool:
        return all(
            (
                self.endpoint,
                self.region,
                self.bucket,
                self.access_key,
                self.secret_key,
                self.passphrase,
            ),
        )


@dataclass(frozen=True, slots=True)
class BackupSettingsUpdate:
    """Новые значения из формы; `None` у секрета — оставить прежний."""

    enabled: bool
    endpoint: str | None
    region: str | None
    bucket: str | None
    access_key: str | None
    secret_key: str | None
    folder: str
    retention_count: int
    passphrase: str | None


def _decrypt_optional(value: str | None) -> str | None:
    return decrypt(value) if value else None


def backup_config(settings: SystemSettings) -> BackupConfig:
    return BackupConfig(
        enabled=settings.backup_enabled,
        endpoint=settings.backup_s3_endpoint,
        region=settings.backup_s3_region,
        bucket=settings.backup_s3_bucket,
        access_key=settings.backup_s3_access_key,
        secret_key=_decrypt_optional(settings.backup_s3_secret_key_encrypted),
        folder=settings.backup_s3_folder,
        retention_count=settings.backup_retention_count,
        passphrase=_decrypt_optional(settings.backup_passphrase_encrypted),
    )


async def load_backup_config(db_session: AsyncSession) -> BackupConfig:
    return backup_config(await get_system_settings(db_session))


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_endpoint(endpoint: str | None) -> str | None:
    value = _blank_to_none(endpoint)
    if value is None:
        return None
    value = value.rstrip("/")
    if not _ENDPOINT_PATTERN.fullmatch(value):
        raise ValidationError("Адрес S3 — https://<хост>[:порт] без пути")
    return value


def _validated(value: str | None, pattern: re.Pattern[str], message: str) -> str | None:
    value = _blank_to_none(value)
    if value is not None and not pattern.fullmatch(value):
        raise ValidationError(message)
    return value


def normalize_folder(folder: str) -> str:
    """Префикс ключей без ведущего и конечного `/`; `..` и пустые сегменты запрещены."""
    value = folder.strip().strip("/")
    segments = value.split("/")
    if (
        not value
        or len(value) > MAX_FOLDER_LENGTH
        or any(
            segment in _RELATIVE_SEGMENTS or not _FOLDER_SEGMENT_PATTERN.fullmatch(segment)
            for segment in segments
        )
    ):
        raise ValidationError(
            "Папка — латиница, цифры, «.», «_», «-», вложенность через «/», без «..»",
        )
    return value


def validate_passphrase(passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise ValidationError(f"Пароль шифрования — не короче {MIN_PASSPHRASE_LENGTH} символов")
    if len(passphrase) > MAX_PASSPHRASE_LENGTH or any(c in passphrase for c in "\r\n\x00"):
        raise ValidationError("Пароль шифрования — одна строка без переводов строк")


def _validated_update(update: BackupSettingsUpdate) -> BackupSettingsUpdate:
    access_key = _validated(update.access_key, _ACCESS_KEY_PATTERN, "Ключ доступа без пробелов")
    if access_key is not None and len(access_key) > MAX_ACCESS_KEY_LENGTH:
        raise ValidationError("Слишком длинный ключ доступа")
    secret_key = update.secret_key or None
    if secret_key is not None and not _ACCESS_KEY_PATTERN.fullmatch(secret_key):
        raise ValidationError("Секретный ключ без пробелов")
    passphrase = update.passphrase or None
    if passphrase is not None:
        validate_passphrase(passphrase)
    return BackupSettingsUpdate(
        enabled=update.enabled,
        endpoint=normalize_endpoint(update.endpoint),
        region=_validated(update.region, _REGION_PATTERN, "Регион — строчные латиница, цифры, «-»"),
        bucket=_validated(update.bucket, _BUCKET_PATTERN, "Имя бакета не по правилам S3"),
        access_key=access_key,
        secret_key=secret_key,
        folder=normalize_folder(update.folder),
        retention_count=update.retention_count,
        passphrase=passphrase,
    )


async def update_backup_settings(
    db_session: AsyncSession,
    *,
    update: BackupSettingsUpdate,
) -> SystemSettings:
    values = _validated_update(update)
    settings = await get_system_settings(db_session)
    settings.backup_s3_endpoint = values.endpoint
    settings.backup_s3_region = values.region
    settings.backup_s3_bucket = values.bucket
    settings.backup_s3_access_key = values.access_key
    if values.secret_key is not None:
        settings.backup_s3_secret_key_encrypted = encrypt(values.secret_key)
    if values.passphrase is not None:
        settings.backup_passphrase_encrypted = encrypt(values.passphrase)
    settings.backup_s3_folder = values.folder
    settings.backup_retention_count = values.retention_count
    if values.enabled and not backup_config(settings).is_complete:
        await db_session.rollback()
        raise ValidationError(
            "Чтобы включить бэкап, заполните адрес, регион, бакет, ключи S3 и пароль шифрования",
        )
    settings.backup_enabled = values.enabled
    await db_session.commit()
    logger.info(
        "backup_settings_updated",
        enabled=settings.backup_enabled,
        secret_key_changed=values.secret_key is not None,
        passphrase_changed=values.passphrase is not None,
    )
    return settings


@dataclass(frozen=True, slots=True)
class ConnectionCheck:
    ok: bool
    message: str


async def check_backup_connection(db_session: AsyncSession) -> ConnectionCheck:
    """
    «Проверить подключение» (раздел 15.5): сохранённые настройки, запись,
    чтение и удаление пробного объекта, создание папки. Без долгих повторов —
    администратор ждёт ответа.
    """
    config = await load_backup_config(db_session)
    try:
        storage = S3Storage.from_config(config, retry_delays=())
        await storage.probe()
        created = await storage.ensure_folder()
    except StorageError as exc:
        logger.info("backup_connection_check_failed", error=str(exc))
        return ConnectionCheck(ok=False, message=str(exc))
    folder_state = "создана" if created else "уже есть"
    return ConnectionCheck(
        ok=True,
        message=(
            f"Подключение работает: запись и чтение прошли, папка {config.folder} {folder_state}"
        ),
    )
