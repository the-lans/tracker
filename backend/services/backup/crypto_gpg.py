"""
Шифрование копии паролем администратора (раздел 20.4 ТЗ): каталог копии
`tar` → `gpg --symmetric` AES-256 одним конвейером, без открытого
промежуточного архива. Расшифровать можно на любой машине с gpg — пароль
спросит сам gpg (`restore.sh`).

Пароль передаётся gpg через отдельный канал (`--passphrase-fd`), а не в
аргументах — в списке процессов его не видно.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app_logging.config import get_logger

logger = get_logger("backup_gpg")

CIPHER_ALGORITHM = "AES256"
_GPG_BASE_ARGS = ("gpg", "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback")


class GpgError(Exception):
    """gpg или tar завершились с ошибкой; текст без пароля."""


def _passphrase_pipe(passphrase: str) -> int:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, passphrase.encode() + b"\n")
    finally:
        os.close(write_fd)
    return read_fd


def _gpg_passphrase_args(fd: int) -> list[str]:
    return [*_GPG_BASE_ARGS, "--passphrase-fd", str(fd)]


@asynccontextmanager
async def _gnupg_home() -> AsyncIterator[str]:
    """
    Отдельный GNUPGHOME на запуск: ключей gpg для симметричного шифрования не
    нужно. Каталог — в коротком системном пути: сокет gpg-agent не создаётся
    при длинном. Агент останавливается сразу, а не по таймауту.
    """
    with tempfile.TemporaryDirectory(prefix="gpg-") as home:
        os.chmod(home, 0o700)
        try:
            yield home
        finally:
            process = await asyncio.create_subprocess_exec(
                "gpgconf",
                "--kill",
                "gpg-agent",
                env={**os.environ, "GNUPGHOME": home},
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()


async def encrypt_directory(directory: Path, target: Path, *, passphrase: str) -> None:
    """`tar -cf - <каталог>` → `gpg --symmetric` → `target`."""
    async with _gnupg_home() as gnupg_home:
        tar_code, gpg_code, gpg_err = await _encrypt(
            directory,
            target,
            passphrase=passphrase,
            gnupg_home=gnupg_home,
        )
    if tar_code != 0 or gpg_code != 0:
        target.unlink(missing_ok=True)
        raise GpgError(f"Не удалось зашифровать копию (tar {tar_code}, gpg {gpg_code}): {gpg_err}")


async def _encrypt(
    directory: Path,
    target: Path,
    *,
    passphrase: str,
    gnupg_home: str,
) -> tuple[int, int, str]:
    passphrase_fd = _passphrase_pipe(passphrase)
    read_fd, write_fd = os.pipe()
    env = {**os.environ, "GNUPGHOME": gnupg_home}
    try:
        tar_process = await asyncio.create_subprocess_exec(
            "tar",
            "-cf",
            "-",
            "-C",
            str(directory.parent),
            directory.name,
            stdout=write_fd,
            stderr=asyncio.subprocess.PIPE,
        )
        gpg_process = await asyncio.create_subprocess_exec(
            *_gpg_passphrase_args(passphrase_fd),
            "--symmetric",
            "--cipher-algo",
            CIPHER_ALGORITHM,
            # Архивы внутри уже сжаты gzip.
            "--compress-algo",
            "none",
            "--output",
            str(target),
            stdin=read_fd,
            stderr=asyncio.subprocess.PIPE,
            pass_fds=(passphrase_fd,),
            env=env,
        )
    finally:
        for fd in (passphrase_fd, read_fd, write_fd):
            os.close(fd)
    (_, _), (_, gpg_err) = await asyncio.gather(
        tar_process.communicate(),
        gpg_process.communicate(),
    )
    return tar_process.returncode or 0, gpg_process.returncode or 0, gpg_err.decode().strip()


async def decrypt_to_directory(source: Path, destination: Path, *, passphrase: str) -> None:
    """`gpg --decrypt source` → `tar -xf - -C destination`."""
    destination.mkdir(parents=True, exist_ok=True)
    async with _gnupg_home() as gnupg_home:
        passphrase_fd = _passphrase_pipe(passphrase)
        read_fd, write_fd = os.pipe()
        env = {**os.environ, "GNUPGHOME": gnupg_home}
        try:
            gpg_process = await asyncio.create_subprocess_exec(
                *_gpg_passphrase_args(passphrase_fd),
                "--decrypt",
                str(source),
                stdout=write_fd,
                stderr=asyncio.subprocess.PIPE,
                pass_fds=(passphrase_fd,),
                env=env,
            )
            tar_process = await asyncio.create_subprocess_exec(
                "tar",
                "-xf",
                "-",
                "-C",
                str(destination),
                stdin=read_fd,
                stderr=asyncio.subprocess.PIPE,
            )
        finally:
            for fd in (passphrase_fd, read_fd, write_fd):
                os.close(fd)
        (_, gpg_err), (_, tar_err) = await asyncio.gather(
            gpg_process.communicate(),
            tar_process.communicate(),
        )
    if gpg_process.returncode != 0:
        raise GpgError(
            "Не удалось расшифровать копию: неверный пароль или повреждённый архив "
            f"({gpg_err.decode(errors='replace').strip()})",
        )
    if tar_process.returncode != 0:
        raise GpgError(f"Не удалось распаковать копию: {tar_err.decode(errors='replace').strip()}")
