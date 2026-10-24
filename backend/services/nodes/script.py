"""
Выполнение script-нод в изолированном Docker-контейнере (раздел 11.4, 19.3 ТЗ).

Требования раздела 19.3, обеспечиваемые здесь при запуске (не образом):
без сети (``--network none``), лимиты CPU/памяти обязательны, без
``--privileged``, монтируются исключительно директория репозиториев
текущей задачи и каталог её артефактов (раздел 14.3), оба read-write.

Файл скрипта пишется во временный файл ВНУТРИ этой же директории
(``.tracker-scripts/``) — контейнеру больше нечего монтировать, чтобы дать
ему доступ к тексту скрипта (раздел 19.3 разрешает монтировать только
директорию репозиториев).

Воркер в продакшене сам работает в контейнере, а `docker run` исполняет
демон хоста: путь `/data/repos/...` из контейнера воркера демону не виден.
Поэтому воркер один раз смотрит `docker inspect` своего контейнера, что
смонтировано в корень репозиториев (и так же — в корень артефактов):
volume — директория задачи монтируется его подпутём (Docker Engine 26+),
каталог хоста — подкаталогом этого каталога. Если воркер не в контейнере
(тесты, запуск на хосте), путь монтируется как есть.

Переменные окружения задачи (раздел 11.4) передаются аргументами
``-e KEY=VALUE``, а не через окружение процесса `docker`: иначе переменная
задачи с именем `PATH` или `DOCKER_HOST` изменила бы поведение самого
клиента Docker. Команда `docker run` в лог не пишется.
"""

from __future__ import annotations

import asyncio
import socket
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app_logging.config import get_logger
from db.models.enums import ScriptLanguage
from services.task_artifacts import resolve_user_files_root
from services.task_workspace import resolve_repos_root

logger = get_logger("nodes.script")

DEFAULT_RUNNER_IMAGES: dict[ScriptLanguage, str] = {
    ScriptLanguage.PYTHON: "tracker-runner-python:latest",
    ScriptLanguage.BASH: "tracker-runner-bash:latest",
}

_SCRIPT_SUBDIR = ".tracker-scripts"
_SCRIPT_SUFFIXES: dict[ScriptLanguage, str] = {
    ScriptLanguage.PYTHON: "py",
    ScriptLanguage.BASH: "sh",
}
# Раздел 19.3 требует лимиты обязательными, но не называет конкретные
# значения — это дефолт реализации, переопределяемый по мере появления
# реальной нагрузки (не часть ТЗ напрямую).
_DEFAULT_MEMORY_LIMIT = "512m"
# Раздел 16.2: метка с моментом, после которого контейнер считается зависшим, —
# по ней `purge_orphaned_docker_containers` не трогает долгие, но живые скрипты.
CONTAINER_DEADLINE_LABEL = "tracker.deadline"
# Запас на остановку по таймауту самой ноды (`docker stop`) сверх `timeout_seconds`.
_DEADLINE_MARGIN_SECONDS = 120
_DEFAULT_CPU_LIMIT = "1.0"
_VOLUME_MOUNT = "volume"


@dataclass(frozen=True, slots=True)
class RootMount:
    """Что демон Docker смонтировал в корень (репозиториев, артефактов) контейнера воркера."""

    type: str
    name: str
    source: str


# Монтирование контейнера не меняется, пока жив процесс воркера: кешируется
# только найденное, неудачная проверка повторяется при следующем запуске.
_root_mount_cache: dict[str, RootMount] = {}
# Docker создаёт этот файл в каждом контейнере.
_CONTAINER_MARKER = Path("/.dockerenv")


class RepositoryMountError(RuntimeError):
    """Воркер в контейнере, но не удалось узнать, что смонтировано в корень директорий задач."""


class ScriptExecutionResult:
    __slots__ = ("exit_code", "stderr", "stdout", "timed_out")

    def __init__(self, *, exit_code: int, stdout: str, stderr: str, timed_out: bool) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out


def container_deadline(timeout_seconds: int, *, now: float | None = None) -> int:
    """Unix-время, после которого контейнер script-ноды считается зависшим."""
    started = time.time() if now is None else now
    return int(started) + timeout_seconds + _DEADLINE_MARGIN_SECONDS


async def run_script_node(
    *,
    script_content: str,
    script_language: ScriptLanguage,
    docker_image: str | None,
    repos_path: Path,
    timeout_seconds: int,
    env: Mapping[str, str] | None = None,
    artifacts_path: Path | None = None,
) -> ScriptExecutionResult:
    """Запускает скрипт в одноразовом (``--rm``) контейнере без сети.

    При истечении ``timeout_seconds`` контейнер принудительно
    останавливается (``docker stop``) — оставлять его висеть до
    периодической уборки (`purge_orphaned_docker_containers`, раздел 16.2)
    без необходимости не нужно, раз момент таймаута точно известен здесь.
    """
    image = docker_image or DEFAULT_RUNNER_IMAGES[script_language]
    mount_args = await task_mount_args(repos_path, artifacts_path)
    scripts_dir = repos_path / _SCRIPT_SUBDIR
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / f"{uuid.uuid4()}.{_SCRIPT_SUFFIXES[script_language]}"
    script_path.write_text(script_content)
    container_name = f"tracker-node-{uuid.uuid4()}"

    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            f"--memory={_DEFAULT_MEMORY_LIMIT}",
            f"--cpus={_DEFAULT_CPU_LIMIT}",
            "--label",
            f"{CONTAINER_DEADLINE_LABEL}={container_deadline(timeout_seconds)}",
            *mount_args,
            *_env_args(env or {}),
            "-w",
            str(repos_path),
            image,
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            timed_out = True
            await _force_stop_container(container_name)
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            # Кнопка «Остановить» (раздел 7.3, 14.2) отменяет корутину ноды —
            # контейнер при этом не должен продолжать работу в фоне.
            await asyncio.shield(_force_stop_container(container_name))
            logger.info("script_node_stopped", image=image)
            raise
        exit_code = process.returncode if process.returncode is not None else -1
    finally:
        script_path.unlink(missing_ok=True)

    logger.info(
        "script_node_finished",
        image=image,
        exit_code=exit_code,
        timed_out=timed_out,
    )
    return ScriptExecutionResult(
        exit_code=exit_code,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
        timed_out=timed_out,
    )


def parse_root_mount(line: str) -> RootMount | None:
    """Строка ``<type> <name> <source>`` из `docker inspect`; пусто — нет монтирования."""
    parts = line.strip("\n").split(" ", 2)
    if len(parts) != 3 or not parts[0]:
        return None
    mount_type, name, source = parts
    return RootMount(type=mount_type, name=name, source=source)


async def _inspect_root_mount(root: Path) -> RootMount | None:
    """Монтирование `root` в своём контейнере; `None` — не в контейнере."""
    destination = str(root.resolve())
    template = (
        "{{range .Mounts}}{{if eq .Destination " + f'"{destination}"'
        + "}}{{.Type}} {{.Name}} {{.Source}}{{end}}{{end}}"
    )
    process = await asyncio.create_subprocess_exec(
        "docker",
        "inspect",
        "--format",
        template,
        socket.gethostname(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return None
    return parse_root_mount(stdout.decode())


async def resolve_root_mount(root: Path) -> RootMount | None:
    """
    `None` — воркер не в контейнере, путь монтируется как есть. В контейнере
    без найденного монтирования путь хоста демону не виден, поэтому вместо
    тихой подмены — ошибка, а проверка повторится при следующем запуске.
    """
    key = str(root.resolve())
    if key in _root_mount_cache:
        return _root_mount_cache[key]
    mount = await _inspect_root_mount(root)
    if mount is not None:
        _root_mount_cache[key] = mount
        logger.info("root_mount_resolved", root=key, mount=str(mount))
        return mount
    if _CONTAINER_MARKER.exists():
        message = (
            f"Не удалось определить через `docker inspect`, что смонтировано в {root} "
            "контейнера воркера"
        )
        raise RepositoryMountError(message)
    return None


def subpath_mount_args(path: Path, root: Path, root_mount: RootMount | None) -> list[str]:
    """Аргументы `docker run`, монтирующие только каталог задачи `path` из `root` (раздел 19.3)."""
    if root_mount is None:
        return ["-v", f"{path}:{path}:rw"]
    real_root = root.resolve()
    try:
        subpath = path.resolve().relative_to(real_root)
    except ValueError as exc:
        message = f"Директория {path} вне корня {real_root}"
        raise ValueError(message) from exc
    if subpath == Path():
        message = f"Директория задачи не может совпадать с корнем {real_root}"
        raise ValueError(message)
    if root_mount.type == _VOLUME_MOUNT:
        return [
            "--mount",
            f"type=volume,src={root_mount.name},dst={path},"
            f"volume-subpath={subpath.as_posix()}",
        ]
    host_path = Path(root_mount.source) / subpath
    return ["-v", f"{host_path}:{path}:rw"]


async def task_mount_args(repos_path: Path, artifacts_path: Path | None) -> list[str]:
    """Директория репозиториев задачи и, если передан, каталог её артефактов."""
    repos_root = resolve_repos_root()
    args = subpath_mount_args(repos_path, repos_root, await resolve_root_mount(repos_root))
    if artifacts_path is not None:
        # Подпуть volume обязан существовать до `docker run`.
        artifacts_path.mkdir(parents=True, exist_ok=True)
        user_files_root = resolve_user_files_root()
        args += subpath_mount_args(
            artifacts_path,
            user_files_root,
            await resolve_root_mount(user_files_root),
        )
    return args


def _env_args(env: Mapping[str, str]) -> list[str]:
    return [arg for key in sorted(env) for arg in ("-e", f"{key}={env[key]}")]


async def _force_stop_container(container_name: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "docker",
        "stop",
        container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate()
