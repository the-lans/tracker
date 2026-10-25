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

Как каталоги задачи монтируются, когда воркер сам работает в контейнере, —
`services/docker_mounts.py` (общий с контейнером сессии).

Переменные окружения задачи (раздел 11.4) передаются аргументами
``-e KEY=VALUE``, а не через окружение процесса `docker`: иначе переменная
задачи с именем `PATH` или `DOCKER_HOST` изменила бы поведение самого
клиента Docker. Команда `docker run` в лог не пишется.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from app_logging.config import get_logger
from db.models.enums import ScriptLanguage
from services.docker_mounts import mount_args
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
    task_mounts = await task_mount_args(repos_path, artifacts_path)
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
            *task_mounts,
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


async def task_mount_args(repos_path: Path, artifacts_path: Path | None) -> list[str]:
    """Директория репозиториев задачи и, если передан, каталог её артефактов."""
    args = await mount_args(repos_path, resolve_repos_root())
    if artifacts_path is not None:
        # Подпуть volume обязан существовать до `docker run`.
        artifacts_path.mkdir(parents=True, exist_ok=True)
        args += await mount_args(artifacts_path, resolve_user_files_root())
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
