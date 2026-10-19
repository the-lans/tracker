"""Выполнение script-нод в изолированном Docker-контейнере (раздел 11.4, 19.3 ТЗ).

Требования раздела 19.3, обеспечиваемые здесь при запуске (не образом):
без сети (``--network none``), лимиты CPU/памяти обязательны, без
``--privileged``, монтируется исключительно директория репозиториев
текущей задачи, в режиме read-write.

Файл скрипта пишется во временный файл ВНУТРИ этой же директории
(``.tracker-scripts/``) — контейнеру больше нечего монтировать, чтобы дать
ему доступ к тексту скрипта (раздел 19.3 разрешает монтировать только
директорию репозиториев).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app_logging.config import get_logger
from db.models.enums import ScriptLanguage

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
_DEFAULT_CPU_LIMIT = "1.0"


class ScriptExecutionResult:
    __slots__ = ("exit_code", "stderr", "stdout", "timed_out")

    def __init__(self, *, exit_code: int, stdout: str, stderr: str, timed_out: bool) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out


async def run_script_node(
    *,
    script_content: str,
    script_language: ScriptLanguage,
    docker_image: str | None,
    repos_path: Path,
    timeout_seconds: int,
) -> ScriptExecutionResult:
    """Запускает скрипт в одноразовом (``--rm``) контейнере без сети.

    При истечении ``timeout_seconds`` контейнер принудительно
    останавливается (``docker stop``) — оставлять его висеть до
    периодической уборки (`purge_orphaned_docker_containers`, раздел 16.2)
    без необходимости не нужно, раз момент таймаута точно известен здесь.
    """
    image = docker_image or DEFAULT_RUNNER_IMAGES[script_language]
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
            "-v",
            f"{repos_path}:{repos_path}:rw",
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


async def _force_stop_container(container_name: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "docker",
        "stop",
        container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await process.communicate()
