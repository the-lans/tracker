"""
Обвязка тестов бэкапа и проверки восстановления: данные volume во
временном каталоге, дамп тестовой БД `pg_dump` её же контейнера (та же
major-версия, что у сервера) и окружение `backup-worker`.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url

from services.backup.archive import ArchiveOptions
from services.backup.bundle import BundleSources
from services.backup.components import ENV_FILE_RELATIVE
from services.backup.dump import DumpCommand, DumpCommandFactory, pg_dump_args
from services.backup.runner import BackupEnvironment
from services.backup.settings import BackupConfig
from services.backup.verify import VerifyEnvironment

PG_TEST_CONTAINER = "tracker_pg_test"
PASSPHRASE = "correct horse battery staple"
ENV_CONTENT = "DOMAIN=tracker.example.com\nSECRET_ENCRYPTION_KEY=example-key\n"
CONFIG = BackupConfig(
    enabled=True,
    endpoint="https://s3.example.com",
    region="ru-1",
    bucket="tracker-test-bucket",
    access_key="AKEXAMPLE",
    secret_key="secret-example",
    folder="Tracker-test",
    retention_count=3,
    passphrase=PASSPHRASE,
)


def make_sources(root: Path) -> BundleSources:
    """Данные volume: обязательные и часть необязательных, `.env` сервера."""
    files = {
        "task_repos/RR-1/app/main.py": "print('hello')\n",
        "task_repos/RR-1/app/.git/HEAD": "ref: refs/heads/feature/RR-1\n",
        "task_repos/RR-1/app/__pycache__/main.cpython-312.pyc": "bytecode",
        "user_files/RR-1/report.md": "# Отчёт\n",
        "log_archive/RR-1/run-1.jsonl.gz": "archived",
        "claude_sessions/RR-1/projects/session.jsonl": '{"type": "user"}\n',
        "claude_sessions/RR-1/cache/big.bin": "cache",
        "cliproxy_data/auths/claude-example.json": '{"token": "example"}',
        "sftp_host_keys/ssh_host_ed25519_key": "host-key-example",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    env_file = root / ENV_FILE_RELATIVE
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(ENV_CONTENT)
    return BundleSources.at(root)


def container_dump_command() -> DumpCommandFactory:
    """pg_dump внутри контейнера тестового PostgreSQL — по сокету, без пароля в argv."""

    def build(snapshot: str) -> DumpCommand:
        return DumpCommand(
            argv=[
                "docker",
                "exec",
                PG_TEST_CONTAINER,
                "pg_dump",
                "-U",
                "tracker",
                "-d",
                make_url(os.environ["DATABASE_URL"]).database or "tracker",
                *pg_dump_args(snapshot),
            ],
            env=dict(os.environ),
        )

    return build


def backup_environment(tmp_path: Path, engine: object) -> BackupEnvironment:
    staging = tmp_path / "staging"
    return BackupEnvironment(
        staging=staging,
        sources=make_sources(tmp_path / "sources"),
        engine=engine,  # type: ignore[arg-type]
        dump_command=container_dump_command(),
        archive_options=ArchiveOptions(retry_delay_seconds=0),
        lock_wait_seconds=0,
    )


def verify_environment(tmp_path: Path) -> VerifyEnvironment:
    return VerifyEnvironment(staging=tmp_path / "verify-staging", lock_wait_seconds=0)


def decrypt_object(body: bytes, target: Path, *, passphrase: str = PASSPHRASE) -> Path:
    """Расшифровывает копию gpg, как это сделал бы администратор; отдаёт каталог копии."""
    encrypted = target / "copy.tar.gpg"
    target.mkdir(parents=True, exist_ok=True)
    encrypted.write_bytes(body)
    with tempfile.TemporaryDirectory(prefix="gpg-") as home:
        decrypted = _gpg_decrypt(encrypted, home=home, passphrase=passphrase)
    subprocess.run(["tar", "-xf", "-", "-C", str(target)], input=decrypted, check=True)
    [directory] = [child for child in target.iterdir() if child.is_dir()]
    return directory


def _gpg_decrypt(encrypted: Path, *, home: str, passphrase: str) -> bytes:
    try:
        return subprocess.run(
            [
                "gpg",
                "--homedir",
                home,
                "--batch",
                "--quiet",
                "--pinentry-mode",
                "loopback",
                "--passphrase-fd",
                "0",
                "--decrypt",
                str(encrypted),
            ],
            input=passphrase.encode() + b"\n",
            capture_output=True,
            check=True,
        ).stdout
    finally:
        subprocess.run(
            ["gpgconf", "--homedir", home, "--kill", "gpg-agent"],
            capture_output=True,
            check=False,
        )
