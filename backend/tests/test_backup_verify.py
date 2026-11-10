"""
Еженедельная проверка восстановления (`services/backup/verify.py`, раздел 20.4
ТЗ): копия снимается настоящим бэкапом в фейковый S3, дамп загружается во
временный контейнер PostgreSQL той же версии, что у сервера.
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from db.models.backups import BackupRun
from db.models.enums import BackupRunKind, BackupRunStatus
from services.backup import runs as runs_module
from services.backup.bundle import AFTER_RESTORE_SQL_NAME, CHECKSUMS_NAME, MANIFEST_NAME
from services.backup.crypto_gpg import encrypt_directory
from services.backup.files import sha256_file
from services.backup.runner import run_backup
from services.backup.runs import BackupError
from services.backup.verify import (
    VERIFY_CONTAINER_LABEL,
    VerifyEnvironment,
    run_verify,
)
from services.notifications import NotificationEvent
from tests.backup_support import CONFIG, backup_environment, decrypt_object, verify_environment
from tests.s3_support import FOLDER, FakeS3Client, fake_storage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User
    from services.backup.storage import S3Storage

_NAME = "tracker-backup-20261111T000000Z.tar.gpg"
_KEY = f"{FOLDER}/{_NAME}"


@pytest_asyncio.fixture
async def engine(run_migrations: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def client() -> FakeS3Client:
    return FakeS3Client()


@pytest.fixture
def storage(client: FakeS3Client) -> S3Storage:
    return fake_storage(client)


@pytest.fixture
def environment(tmp_path: Path) -> VerifyEnvironment:
    return verify_environment(tmp_path)


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> list[NotificationEvent]:
    sent: list[NotificationEvent] = []

    async def record(
        _session: object, *, event: NotificationEvent, user_id: object, detail: str
    ) -> None:
        sent.append(event)

    monkeypatch.setattr(runs_module, "notify_user_event", record)
    return sent


@pytest_asyncio.fixture
async def backed_up(
    db_session: AsyncSession,
    redis_client: Redis,
    storage: S3Storage,
    engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    await run_backup(
        db_session,
        redis_client,
        config=CONFIG,
        storage=storage,
        environment=backup_environment(tmp_path / "backup", engine),
        started_at=datetime(2026, 11, 11, tzinfo=UTC),
    )


async def _verify(
    db_session: AsyncSession,
    redis_client: Redis,
    storage: S3Storage,
    environment: VerifyEnvironment,
    **config_changes: Any,
) -> BackupRun:
    return await run_verify(
        db_session,
        redis_client,
        config=replace(CONFIG, **config_changes),
        storage=storage,
        environment=environment,
    )


async def _replace_copy(
    client: FakeS3Client,
    tmp_path: Path,
    change: Callable[[Path], None],
) -> None:
    """Перешифровывает копию с изменённым содержимым и честной SHA-256 объекта."""
    bundle = decrypt_object(client.objects[_KEY].body, tmp_path / "tamper")
    change(bundle)
    encrypted = tmp_path / "tampered.tar.gpg"
    await encrypt_directory(bundle, encrypted, passphrase=CONFIG.passphrase or "")
    client.objects[_KEY].body = encrypted.read_bytes()
    client.objects[_KEY].metadata["sha256"] = sha256_file(encrypted)


def _rewrite_sums(bundle: Path) -> None:
    lines = [
        f"{sha256_file(path)}  {path.name}"
        for path in sorted(bundle.iterdir())
        if path.is_file() and path.name != CHECKSUMS_NAME
    ]
    (bundle / CHECKSUMS_NAME).write_text("\n".join(lines) + "\n")


def _leftover_containers() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={VERIFY_CONTAINER_LABEL}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


@pytest.mark.usefixtures("backed_up")
class TestVerify:
    async def test_success(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: VerifyEnvironment,
    ) -> None:
        run = await _verify(db_session, redis_client, storage, environment)

        assert run.status is BackupRunStatus.SUCCESS
        assert run.object_key == _KEY
        assert run.details["tables"] > 20
        assert {item["name"] for item in run.details["components"]} >= {
            "task_repos",
            "user_files",
        }
        assert list(environment.staging.iterdir()) == []
        assert _leftover_containers() == []

    async def test_wrong_passphrase(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: VerifyEnvironment,
        admin_user: User,
        notifications: list[NotificationEvent],
    ) -> None:
        with pytest.raises(BackupError, match="неверный пароль"):
            await _verify(
                db_session,
                redis_client,
                storage,
                environment,
                passphrase="another passphrase entirely",
            )

        run = await db_session.scalar(
            sa.select(BackupRun).where(BackupRun.kind == BackupRunKind.VERIFY),
        )
        assert run is not None and run.status is BackupRunStatus.FAILED
        assert notifications == [NotificationEvent.BACKUP_VERIFY_FAILED]

    async def test_object_corrupted(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: VerifyEnvironment,
    ) -> None:
        client.objects[_KEY].body = client.objects[_KEY].body[:-1] + b"\x00"

        with pytest.raises(BackupError, match="SHA-256"):
            await _verify(db_session, redis_client, storage, environment)

    async def test_file_changed_inside(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: VerifyEnvironment,
        tmp_path: Path,
    ) -> None:
        def change_env(bundle: Path) -> None:
            (bundle / ".env").write_text("DOMAIN=changed\n")

        await _replace_copy(client, tmp_path, change_env)

        with pytest.raises(BackupError, match=r"контрольные суммы: \.env"):
            await _verify(db_session, redis_client, storage, environment)

    async def test_archive_broken(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: VerifyEnvironment,
        tmp_path: Path,
    ) -> None:
        def truncate(bundle: Path) -> None:
            archive = bundle / "task_repos.tar.gz"
            archive.write_bytes(archive.read_bytes()[:40])
            _rewrite_sums(bundle)

        await _replace_copy(client, tmp_path, truncate)

        with pytest.raises(BackupError, match="task_repos.tar.gz не читается"):
            await _verify(db_session, redis_client, storage, environment)

    async def test_dump_does_not_load(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: VerifyEnvironment,
        tmp_path: Path,
    ) -> None:
        def break_dump(bundle: Path) -> None:
            manifest = json.loads((bundle / MANIFEST_NAME).read_text())
            dump = bundle / manifest["database"]["file"]
            text = gzip.decompress(dump.read_bytes()).decode()
            dump.write_bytes(gzip.compress((text + "\nSELECT * FROM missing_table;\n").encode()))
            _rewrite_sums(bundle)

        await _replace_copy(client, tmp_path, break_dump)

        with pytest.raises(BackupError, match="не загрузился в чистый PostgreSQL"):
            await _verify(db_session, redis_client, storage, environment)
        assert _leftover_containers() == []

    async def test_after_restore_sql_fails(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: VerifyEnvironment,
        tmp_path: Path,
    ) -> None:
        """Проверка выполняет after-restore.sql, как install.sh --restore."""

        def break_after_restore(bundle: Path) -> None:
            (bundle / AFTER_RESTORE_SQL_NAME).write_text("UPDATE missing_table SET x = 1;\n")
            _rewrite_sums(bundle)

        await _replace_copy(client, tmp_path, break_after_restore)

        with pytest.raises(BackupError, match="missing_table"):
            await _verify(db_session, redis_client, storage, environment)

    async def test_row_counts_differ(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: VerifyEnvironment,
        tmp_path: Path,
    ) -> None:
        def inflate_counts(bundle: Path) -> None:
            manifest_path = bundle / MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text())
            manifest["database"]["table_counts"]["system_settings"] += 5
            manifest_path.write_text(json.dumps(manifest))
            _rewrite_sums(bundle)

        await _replace_copy(client, tmp_path, inflate_counts)

        with pytest.raises(BackupError, match="system_settings"):
            await _verify(db_session, redis_client, storage, environment)


class TestNothingToVerify:
    async def test_empty_storage(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: VerifyEnvironment,
    ) -> None:
        with pytest.raises(BackupError, match="нет ни одной копии"):
            await _verify(db_session, redis_client, storage, environment)
