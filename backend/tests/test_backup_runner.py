"""
Ежедневный бэкап в S3 (`services/backup/runner.py`, раздел 20.4 ТЗ):
настоящие дамп тестовой БД и gpg, хранилище — фейковый клиент S3.
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from db.models.backups import BackupRun
from db.models.enums import (
    BackupRunKind,
    BackupRunStatus,
    PeriodicRunStatus,
    PeriodicScheduleType,
)
from db.models.periodic import PeriodicTask
from services.backup import jobs as backup_jobs
from services.backup import runner as runner_module
from services.backup import runs as runs_module
from services.backup.archive import REASON_LOCKED, SkippedFile
from services.backup.bundle import (
    AFTER_RESTORE_SQL_NAME,
    BACKUP_PERIODIC_TASK,
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    after_restore_sql,
)
from services.backup.components import COMPONENTS
from services.backup.runner import BackupEnvironment, rotate, run_backup
from services.backup.runs import BACKUP_LOCK_KEY, BackupError
from services.backup.settings import BackupSettingsUpdate, update_backup_settings
from services.notifications import NotificationEvent
from tasks.celery_app import BACKUP_TO_S3
from tests.backup_support import (
    CONFIG,
    ENV_CONTENT,
    PASSPHRASE,
    backup_environment,
    decrypt_object,
)
from tests.s3_support import FOLDER, FakeS3Client, client_error, fake_storage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User
    from services.backup.storage import S3Storage

_STARTED_AT = datetime(2026, 11, 11, 0, 0, tzinfo=UTC)
_NAME = "tracker-backup-20261111T000000Z.tar.gpg"
_RESTORE_SCRIPT = (
    Path(__file__).resolve().parents[1] / "services" / "backup" / "templates" / "restore.sh"
)


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
def environment(tmp_path: Path, engine: AsyncEngine) -> BackupEnvironment:
    return backup_environment(tmp_path, engine)


@pytest.fixture
def notifications(monkeypatch: pytest.MonkeyPatch) -> list[tuple[NotificationEvent, str]]:
    sent: list[tuple[NotificationEvent, str]] = []

    async def record(
        _session: object, *, event: NotificationEvent, user_id: object, detail: str
    ) -> None:
        sent.append((event, detail))

    monkeypatch.setattr(runs_module, "notify_user_event", record)
    return sent


async def _backup(
    db_session: AsyncSession,
    redis_client: Redis,
    storage: S3Storage,
    environment: BackupEnvironment,
    *,
    started_at: datetime = _STARTED_AT,
    **config_changes: Any,
) -> BackupRun:
    return await run_backup(
        db_session,
        redis_client,
        config=replace(CONFIG, **config_changes),
        storage=storage,
        environment=environment,
        started_at=started_at,
    )


async def _runs(db_session: AsyncSession) -> list[BackupRun]:
    return list(
        (
            await db_session.scalars(
                sa.select(BackupRun).where(BackupRun.kind == BackupRunKind.BACKUP),
            )
        ).all(),
    )


class TestFullBackup:
    async def test_contents(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: BackupEnvironment,
        tmp_path: Path,
    ) -> None:
        run = await _backup(db_session, redis_client, storage, environment)

        assert run.status is BackupRunStatus.SUCCESS
        assert run.object_key == f"{FOLDER}/{_NAME}"
        blob = client.objects[f"{FOLDER}/{_NAME}"]
        assert blob.metadata["sha256"] == run.sha256
        assert b"SECRET_ENCRYPTION_KEY" not in blob.body
        assert {f"{FOLDER}/RESTORE.md", f"{FOLDER}/restore.sh"} <= set(client.objects)
        guide = client.objects[f"{FOLDER}/RESTORE.md"].body.decode()
        assert "https://s3.example.com" in guide and "secret-example" not in guide

        bundle = decrypt_object(blob.body, tmp_path / "decrypted")
        assert bundle.name == "tracker-backup-20261111T000000Z"
        assert (bundle / ".env").read_text() == ENV_CONTENT
        assert (bundle / ".env").stat().st_mode & 0o777 == 0o600
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())
        assert {item["name"] for item in manifest["components"]} == {
            component.name for component in COMPONENTS
        }
        [accounts] = [item for item in manifest["components"] if item["name"] == "claude_accounts"]
        assert accounts == {"name": "claude_accounts", "present": False}
        database = manifest["database"]
        assert database["alembic_version"]
        assert database["table_counts"]["system_settings"] >= 0
        dump = gzip.decompress((bundle / database["file"]).read_bytes()).decode()
        assert "CREATE TABLE public.tasks" in dump
        # Права роли SFTP-шлюза выдаёт entrypoint, в дампе их нет.
        assert "GRANT" not in dump
        listed = {
            line.split("  ", 1)[1]
            for line in (bundle / CHECKSUMS_NAME).read_text().split("\n")
            if line
        }
        assert listed == {path.name for path in bundle.iterdir()} - {CHECKSUMS_NAME}
        assert list(environment.staging.iterdir()) == []

    async def test_restore_script_extracts(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: BackupEnvironment,
        tmp_path: Path,
    ) -> None:
        """`restore.sh --extract-only` без Docker и root: проверка сумм и распаковка volume."""
        await _backup(db_session, redis_client, storage, environment)
        encrypted = tmp_path / _NAME
        encrypted.write_bytes(client.objects[f"{FOLDER}/{_NAME}"].body)
        passphrase_file = tmp_path / "passphrase"
        passphrase_file.write_text(PASSPHRASE + "\n")
        # Короткий каталог: путь сокета gpg-agent в tmp_path длиннее предела.
        with tempfile.TemporaryDirectory(prefix="gpg-") as gnupg_home:
            result = subprocess.run(
                [
                    "bash",
                    str(_RESTORE_SCRIPT),
                    str(encrypted),
                    "--extract-only",
                    str(tmp_path / "out"),
                ],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "BACKUP_PASSPHRASE_FILE": str(passphrase_file),
                    "GNUPGHOME": gnupg_home,
                },
                check=False,
            )
            subprocess.run(
                ["gpgconf", "--kill", "gpg-agent"],
                env={**os.environ, "GNUPGHOME": gnupg_home},
                check=False,
            )

        assert result.returncode == 0, result.stdout + result.stderr
        volumes = tmp_path / "out" / "volumes"
        assert (volumes / "task_repos/RR-1/app/main.py").read_text() == "print('hello')\n"
        assert (volumes / "task_repos/RR-1/app/.git/HEAD").exists()
        assert not (volumes / "task_repos/RR-1/app/__pycache__").exists()
        assert not (volumes / "claude_sessions/RR-1/cache").exists()
        assert (volumes / "sftp_host_keys/ssh_host_ed25519_key").exists()


async def _execute_script(db_session: AsyncSession, sql: str) -> None:
    """
    Несколько команд, как их выполняет psql в install.sh: простой протокол
    asyncpg — в той же транзакции теста.
    """
    connection = await db_session.connection()
    raw = await connection.get_raw_connection()
    await raw.driver_connection.execute(sql)  # type: ignore[union-attr]


def _backup_periodic_task(status: PeriodicRunStatus) -> PeriodicTask:
    return PeriodicTask(
        id=uuid.uuid4(),
        name=BACKUP_PERIODIC_TASK,
        display_name="Бэкап",
        description="d",
        task_path="tasks.periodic.backup_to_s3",
        schedule_type=PeriodicScheduleType.CRONTAB,
        crontab_expression="0 0 * * *",
        last_run_status=status,
    )


async def _reload[T](db_session: AsyncSession, row: T) -> T:
    db_session.expunge(row)
    reloaded = await db_session.get(type(row), row.id)  # type: ignore[attr-defined]
    assert reloaded is not None
    return reloaded


class TestAfterRestore:
    """
    Дамп снят во время запуска бэкапа: `after-restore.sql` записывает
    итог копии этому запуску и периодической задаче.
    """

    def test_task_name(self) -> None:
        assert BACKUP_PERIODIC_TASK == BACKUP_TO_S3

    async def test_in_bundle(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: BackupEnvironment,
        tmp_path: Path,
    ) -> None:
        run = await _backup(db_session, redis_client, storage, environment)

        bundle = decrypt_object(client.objects[f"{FOLDER}/{_NAME}"].body, tmp_path / "out")
        sql = (bundle / AFTER_RESTORE_SQL_NAME).read_text()
        assert f"id = '{run.id}'" in sql
        assert f"object_key = '{FOLDER}/{_NAME}'" in sql
        assert AFTER_RESTORE_SQL_NAME in (bundle / CHECKSUMS_NAME).read_text()

    @pytest.mark.parametrize(
        ("skipped", "status"),
        [
            ([], BackupRunStatus.SUCCESS),
            (
                [SkippedFile(component="task_repos", path="RR-1/it's.txt", reason=REASON_LOCKED)],
                BackupRunStatus.WARNING,
            ),
        ],
        ids=["success", "skipped"],
    )
    async def test_closes_running(
        self,
        db_session: AsyncSession,
        skipped: list[SkippedFile],
        status: BackupRunStatus,
    ) -> None:
        run = BackupRun(id=uuid.uuid4(), kind=BackupRunKind.BACKUP, status=BackupRunStatus.RUNNING)
        periodic = _backup_periodic_task(PeriodicRunStatus.RUNNING)
        db_session.add_all([run, periodic])
        await db_session.commit()
        sql = after_restore_sql(
            run_id=run.id,
            object_key=f"{FOLDER}/{_NAME}",
            skipped=skipped,
            finished_at=_STARTED_AT,
        )

        # Повторное выполнение ничего не меняет.
        await _execute_script(db_session, sql)
        await _execute_script(db_session, sql)

        restored = await _reload(db_session, run)
        assert (restored.status, restored.object_key, restored.finished_at) == (
            status,
            f"{FOLDER}/{_NAME}",
            _STARTED_AT,
        )
        assert restored.skipped_files == [item.as_dict() for item in skipped]
        task = await _reload(db_session, periodic)
        assert (task.last_run_status, task.last_run_at) == (PeriodicRunStatus.SUCCESS, _STARTED_AT)

    async def test_finished_run_untouched(self, db_session: AsyncSession) -> None:
        """Дамп, где запуск и задача уже завершены (или их нет), файл не меняет."""
        run = BackupRun(
            id=uuid.uuid4(),
            kind=BackupRunKind.BACKUP,
            status=BackupRunStatus.FAILED,
            error_message="сбой",
        )
        periodic = _backup_periodic_task(PeriodicRunStatus.FAILED)
        db_session.add_all([run, periodic])
        await db_session.commit()

        await _execute_script(
            db_session,
            after_restore_sql(run_id=run.id, object_key="k", skipped=[], finished_at=_STARTED_AT),
        )

        assert (await _reload(db_session, run)).status is BackupRunStatus.FAILED
        assert (await _reload(db_session, periodic)).last_run_status is PeriodicRunStatus.FAILED


class TestRotation:
    async def test_keeps_newest(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: BackupEnvironment,
    ) -> None:
        for day in ("08", "09", "10"):
            await storage.put_text(
                f"tracker-backup-202611{day}T000000Z.tar.gpg",
                "old",
                content_type="application/octet-stream",
            )

        run = await _backup(db_session, redis_client, storage, environment, retention_count=2)

        assert client.backup_keys() == [
            f"{FOLDER}/tracker-backup-20261110T000000Z.tar.gpg",
            f"{FOLDER}/{_NAME}",
        ]
        assert run.details["rotated"] == [
            "tracker-backup-20261108T000000Z.tar.gpg",
            "tracker-backup-20261109T000000Z.tar.gpg",
        ]

    @pytest.mark.parametrize(
        ("existing", "keep", "deleted"),
        [
            (["a", "b"], 3, []),
            (["a", "b"], 2, ["a"]),
            (["a", "b", "c"], 1, ["a", "b", "c"]),
        ],
    )
    async def test_never_deletes_current(
        self,
        client: FakeS3Client,
        storage: S3Storage,
        existing: list[str],
        keep: int,
        deleted: list[str],
    ) -> None:
        names = [f"tracker-backup-{suffix}.tar.gpg" for suffix in existing]
        for name in names:
            await storage.put_text(name, "x", content_type="text/plain")
        current = "tracker-backup-z.tar.gpg"
        await storage.put_text(current, "x", content_type="text/plain")

        result = await rotate(storage, keep=keep, current=current)

        assert result == [f"tracker-backup-{suffix}.tar.gpg" for suffix in deleted]
        assert f"{FOLDER}/{current}" in client.objects

    async def test_failed_upload_keeps_old(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: BackupEnvironment,
        admin_user: User,
        notifications: list[tuple[NotificationEvent, str]],
    ) -> None:
        """Новая копия не прошла проверку загрузки — старые не удаляются."""
        old = [f"tracker-backup-2026110{day}T000000Z.tar.gpg" for day in (1, 2, 3)]
        for name in old:
            await storage.put_text(name, "old", content_type="application/octet-stream")
        original_upload = client.upload_file

        def upload_then_corrupt(*args: Any, **kwargs: Any) -> None:
            original_upload(*args, **kwargs)
            client.objects[f"{FOLDER}/{_NAME}"].body += b"!"

        client.upload_file = upload_then_corrupt  # type: ignore[method-assign]

        with pytest.raises(BackupError, match="не совпадает"):
            await _backup(db_session, redis_client, storage, environment, retention_count=1)

        assert {f"{FOLDER}/{name}" for name in old} <= set(client.objects)
        [run] = await _runs(db_session)
        assert run.status is BackupRunStatus.FAILED
        assert notifications == [(NotificationEvent.BACKUP_FAILED, run.error_message)]
        assert list(environment.staging.iterdir()) == []


class TestFailures:
    async def test_lock_busy(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: BackupEnvironment,
        admin_user: User,
        notifications: list[tuple[NotificationEvent, str]],
    ) -> None:
        await redis_client.set(BACKUP_LOCK_KEY, "other", ex=60)
        try:
            with pytest.raises(BackupError, match="ещё не закончились"):
                await _backup(db_session, redis_client, storage, environment)
        finally:
            await redis_client.delete(BACKUP_LOCK_KEY)

        [run] = await _runs(db_session)
        assert run.status is BackupRunStatus.FAILED
        assert len(notifications) == 1

    async def test_not_enough_space(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: BackupEnvironment,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(runner_module, "required_space", lambda _sources: 10**18)

        with pytest.raises(BackupError, match="Недостаточно места"):
            await _backup(db_session, redis_client, storage, environment)

        assert client.backup_keys() == []

    async def test_missing_required_volume(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: BackupEnvironment,
    ) -> None:
        (environment.sources.root / "user_files").rename(environment.sources.root / "moved")

        with pytest.raises(BackupError, match="user_files"):
            await _backup(db_session, redis_client, storage, environment)

    async def test_storage_denied(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        client: FakeS3Client,
        storage: S3Storage,
        environment: BackupEnvironment,
    ) -> None:
        client.failures["head"] = [client_error("AccessDenied")]

        with pytest.raises(BackupError, match="Доступ запрещён"):
            await _backup(db_session, redis_client, storage, environment)

        [run] = await _runs(db_session)
        assert "secret-example" not in (run.error_message or "")

    async def test_unexpected_error_hides_text(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: BackupEnvironment,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(_sources: object) -> int:
            raise KeyError("postgresql://tracker:password@db")

        monkeypatch.setattr(runner_module, "required_space", broken)

        with pytest.raises(BackupError, match="Внутренняя ошибка: KeyError"):
            await _backup(db_session, redis_client, storage, environment)

        [run] = await _runs(db_session)
        assert "password" not in (run.error_message or "")


async def _add_run(
    db_session: AsyncSession,
    *,
    kind: BackupRunKind,
    status: BackupRunStatus,
    started_at: datetime,
) -> BackupRun:
    run = BackupRun(id=uuid.uuid4(), kind=kind, status=status, started_at=started_at)
    db_session.add(run)
    await db_session.commit()
    return run


class TestInterruptedRuns:
    """Запуск, чей процесс убили, закрывает следующий запуск под блокировкой."""

    @pytest.mark.parametrize("kind", [BackupRunKind.BACKUP, BackupRunKind.VERIFY])
    async def test_closed_by_next_backup(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: BackupEnvironment,
        monkeypatch: pytest.MonkeyPatch,
        kind: BackupRunKind,
    ) -> None:
        orphan = await _add_run(
            db_session,
            kind=kind,
            status=BackupRunStatus.RUNNING,
            started_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        monkeypatch.setattr(runner_module, "required_space", lambda _sources: 10**18)

        with pytest.raises(BackupError, match="Недостаточно места"):
            await _backup(db_session, redis_client, storage, environment)

        await db_session.refresh(orphan)
        assert orphan.status is BackupRunStatus.FAILED
        assert orphan.error_message == runs_module.INTERRUPTED_MESSAGE
        assert orphan.finished_at is not None

    async def test_later_and_finished_untouched(self, db_session: AsyncSession) -> None:
        current = await _add_run(
            db_session,
            kind=BackupRunKind.BACKUP,
            status=BackupRunStatus.RUNNING,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        waiting = await _add_run(
            db_session,
            kind=BackupRunKind.VERIFY,
            status=BackupRunStatus.RUNNING,
            started_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        finished = await _add_run(
            db_session,
            kind=BackupRunKind.BACKUP,
            status=BackupRunStatus.SUCCESS,
            started_at=datetime(2020, 1, 1, tzinfo=UTC),
        )

        closed = await runs_module.close_interrupted_runs(db_session, current=current)

        assert closed == 0
        for run in (current, waiting, finished):
            await db_session.refresh(run)
        assert [current.status, waiting.status, finished.status] == [
            BackupRunStatus.RUNNING,
            BackupRunStatus.RUNNING,
            BackupRunStatus.SUCCESS,
        ]


class TestSkippedFiles:
    async def test_warning(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        storage: S3Storage,
        environment: BackupEnvironment,
    ) -> None:
        git_dir = environment.sources.root / "task_repos/RR-1/app/.git"
        (git_dir / "index").write_text("index")
        (git_dir / "index.lock").write_text("")

        run = await _backup(db_session, redis_client, storage, environment)

        assert run.status is BackupRunStatus.WARNING
        assert run.skipped_files == [
            {"component": "task_repos", "path": "RR-1/app/.git/index", "reason": REASON_LOCKED},
        ]


class TestJob:
    async def test_not_configured_is_noop(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[object] = []
        monkeypatch.setattr(backup_jobs, "run_backup", lambda *args, **kwargs: calls.append(args))
        await update_backup_settings(
            db_session,
            update=BackupSettingsUpdate(
                enabled=False,
                endpoint="https://s3.example.com",
                region="ru-1",
                bucket="tracker-backups",
                access_key="AKEXAMPLE",
                secret_key="secret-example",
                folder="Tracker",
                retention_count=7,
                passphrase=PASSPHRASE,
            ),
        )

        await backup_jobs.backup_job(db_session, now=_STARTED_AT)
        await backup_jobs.verify_job(db_session)

        assert calls == []
        assert await _runs(db_session) == []
