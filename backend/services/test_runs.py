"""
Общий жизненный цикл проверок из API, нод и инструментов агента.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import json
import os
import shutil
import signal
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import TaskStatus
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from db.models.test_runs import TestRun
from db.session import async_session_factory
from services.ci_turn_gate import gate_key, request_key, reservation_key
from services.claude_config import resolve_sessions_root
from services.distributed_lock import (
    LockNotAcquiredError,
    acquire_task_operation_lock,
    lock_key,
    wait_for_lock,
)
from services.docker_mounts import mount_args, resolve_root_mount
from services.errors import ConflictError, NotFoundError, ValidationError
from services.redis_connection import redis_connection
from services.task_artifacts import task_artifacts_dir
from services.task_workspace import prepare_task_workspace, resolve_repos_root, task_repos_path
from services.test_profile_types import TestProfile

ACTIVE_STATUSES = ("queued", "agent", "preparing", "running")
MAX_LOG_BYTES = 1_000_000
RUN_DIRECTORY = ".tracker-test-runs"
STALE_SECONDS = 120
POLL_SECONDS = 1
LOG_CHUNK_BYTES = 8192
ERROR_OUTPUT_CHARS = 4000
DOCKER_COMMAND_TIMEOUT_SECONDS = 60
WORKSPACE_LOCK_SECONDS = 300
WORKSPACE_WAIT_SECONDS = 120
CLEANUP_LOCK_SECONDS = 600
DEPENDENCY_WAIT_SECONDS = 120
DEPENDENCY_HEALTH_RETRIES = 60
RUN_HEARTBEAT_SECONDS = 5
COMPOSE_RENDER_IMAGE = "docker:27.5.1-cli"
COMPOSE_RENDER_MEMORY = "512m"
COMPOSE_RENDER_CPUS = "1"


def run_directory(task: Task, run_id: uuid.UUID) -> Path:
    return Path(task_repos_path(task)) / RUN_DIRECTORY / str(run_id)


def project_name(run_id: uuid.UUID) -> str:
    return f"tracker-check-{run_id.hex}"


async def create_run(
    db: AsyncSession,
    *,
    task: Task,
    repository_id: uuid.UUID,
    check: str,
    source: str,
    idempotency_key: uuid.UUID,
    commit: bool = True,
    profile_snapshot: dict[str, Any] | None = None,
) -> TestRun:
    existing = await db.scalar(
        sa.select(TestRun).where(
            TestRun.task_id == task.id,
            TestRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.repository_id != repository_id or existing.check != check:
            raise ConflictError("Ключ повторного запуска уже используется другой проверкой")
        return existing
    locked = await db.scalar(
        sa.select(Task)
        .where(Task.id == task.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise NotFoundError("Задача не найдена")
    if source != "manual" and locked.status in (TaskStatus.DONE, TaskStatus.ARCHIVED):
        raise ConflictError("Автоматический запуск проверки у завершённой задачи недоступен")
    repository = await db.scalar(
        sa.select(Repository)
        .join(
            TaskRepository,
            TaskRepository.repository_id == Repository.id,
        )
        .where(Repository.id == repository_id, TaskRepository.task_id == task.id)
    )
    if repository is None:
        raise NotFoundError("Репозиторий не привязан к задаче")
    if profile_snapshot is None and repository.test_profile is None:
        raise ValidationError("В настройках репозитория не задан профиль тестирования")
    profile = TestProfile.model_validate(profile_snapshot or repository.test_profile)
    if check not in profile.commands:
        raise ValidationError("Проверка отсутствует в профиле репозитория")
    if source == "ci-agent" and check == "unit":
        profile.commands["unit"] = (
            "tracker_ci_unit_exit=0\n"
            f"(\n{profile.commands['unit']}\n) || tracker_ci_unit_exit=$?\n"
            "tracker_ci_lint_exit=0\n"
            f"(\n{profile.commands['lint']}\n) || tracker_ci_lint_exit=$?\n"
            "printf 'Unit exit code: %s; lint exit code: %s\\n' "
            '"$tracker_ci_unit_exit" "$tracker_ci_lint_exit"\n'
            'if [ "$tracker_ci_unit_exit" -ne 0 ]; then exit "$tracker_ci_unit_exit"; fi\n'
            'exit "$tracker_ci_lint_exit"'
        )
    values = dict(
        id=uuid.uuid4(),
        task_id=task.id,
        repository_id=repository.id,
        idempotency_key=idempotency_key,
        check=check,
        source=source,
        profile=profile.model_dump(),
        repository_name=repository.name,
        status="queued",
        cleanup_status="pending",
        logs="",
        report_files=[],
        cancel_requested=False,
    )
    await db.execute(
        insert(TestRun)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["task_id", "idempotency_key"],
        )
    )
    if commit:
        await db.commit()
    result = await db.scalar(
        sa.select(TestRun).where(
            TestRun.task_id == task.id,
            TestRun.idempotency_key == idempotency_key,
        )
    )
    assert result is not None
    if result.repository_id != repository_id or result.check != check:
        raise ConflictError("Ключ повторного запуска уже используется другой проверкой")
    return result


async def update_run(run_id: uuid.UUID, **values: Any) -> None:
    async with async_session_factory() as db:
        await db.execute(sa.update(TestRun).where(TestRun.id == run_id).values(**values))
        await db.commit()


def redact(text: str, environment: dict[str, str]) -> str:
    for value in sorted(environment.values(), key=len, reverse=True):
        if len(value) >= 4:
            text = text.replace(value, "***")
    return text


async def cancelled(run_id: uuid.UUID) -> bool:
    async with async_session_factory() as db:
        return bool(
            await db.scalar(sa.select(TestRun.cancel_requested).where(TestRun.id == run_id))
        )


class RunCancelled(Exception):
    pass


class ComposeExecutor:
    def __init__(self, run: TestRun, directory: Path):
        self.run = run
        self.directory = directory
        self.logs = run.logs
        docker_environment = {
            "PATH",
            "HOME",
            "TMPDIR",
            "DOCKER_HOST",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "SSL_CERT_FILE",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
        }
        self.environment = {
            key: value for key, value in os.environ.items() if key in docker_environment
        }
        # Compose получает явно заданные файлы и собственное имя проекта.
        self.environment.pop("COMPOSE_FILE", None)
        self.environment.pop("COMPOSE_PROJECT_NAME", None)

    async def command(self, args: list[str], *, capture: bool = False) -> str:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.directory,
            env=self.environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if capture else asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        output = bytearray()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        async def read() -> None:
            assert process.stdout is not None
            while chunk := await process.stdout.read(LOG_CHUNK_BYTES):
                output.extend(chunk)
                if not capture and len(output) > MAX_LOG_BYTES:
                    del output[:-MAX_LOG_BYTES]
                if not capture:
                    self.logs = (self.logs + decoder.decode(chunk))[-MAX_LOG_BYTES:]
                    self.logs = redact(self.logs, self.run.profile.get("environment", {}))
                    await update_run(self.run.id, logs=self.logs)

        reader = asyncio.create_task(read())
        stderr_reader = (
            asyncio.create_task(process.stderr.read()) if process.stderr is not None else None
        )
        stderr = b""
        try:
            while process.returncode is None:
                if await cancelled(self.run.id):
                    raise RunCancelled
                await update_run(self.run.id, heartbeat_at=datetime.now(UTC))
                try:
                    await asyncio.wait_for(process.wait(), POLL_SECONDS)
                except TimeoutError:
                    continue
            await reader
            if stderr_reader is not None:
                stderr = await stderr_reader
                if stderr:
                    self.logs = redact(
                        (self.logs + stderr.decode(errors="replace"))[-MAX_LOG_BYTES:],
                        self.run.profile.get("environment", {}),
                    )
                    await update_run(self.run.id, logs=self.logs)
        finally:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            if not reader.done():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader
            if stderr_reader is not None and not stderr_reader.done():
                stderr_reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_reader
        text = output.decode(errors="replace")
        if process.returncode:
            text += stderr.decode(errors="replace")
            raise ComposeFailed(
                process.returncode,
                redact(
                    text[-ERROR_OUTPUT_CHARS:],
                    self.run.profile.get(
                        "environment",
                        {},
                    ),
                ),
            )
        return text

    def compose(self, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-name",
            project_name(self.run.id),
            "--file",
            str(self.directory / "compose.json"),
            *args,
        ]


class ComposeFailed(Exception):
    def __init__(self, exit_code: int, output: str):
        self.exit_code = exit_code
        super().__init__(f"Код возврата {exit_code}. {output}")


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValidationError("Путь выходит за пределы репозитория")
    return path


def snapshot_repository(source: Path, target: Path) -> None:
    if not (source / ".git").exists():
        raise ValidationError("Рабочая копия репозитория ещё не подготовлена")
    shutil.copytree(
        source,
        target,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "node_modules",
            "__pycache__",
            RUN_DIRECTORY,
            "tmp",
            ".env",
            ".env.local",
        ),
    )


async def isolated_config(
    config: dict[str, Any],
    *,
    snapshot: Path,
    run_id: uuid.UUID,
) -> dict[str, Any]:
    """
    Преобразует Compose в окружение без общих портов, сетей и данных.
    """
    name = project_name(run_id)
    mount = await resolve_root_mount(resolve_repos_root())
    volumes: dict[str, Any] = {}
    for key, value in config.get("volumes", {}).items():
        if value and value.get("external"):
            raise ValidationError("В тестовом окружении недоступны внешние тома")
        volumes[key] = {
            "name": f"{name}-{key}",
            "labels": {"tracker.test_run": str(run_id)},
        }
    networks: dict[str, Any] = {}
    for key, value in config.get("networks", {"default": {}}).items():
        if value and value.get("external"):
            raise ValidationError("В тестовом окружении недоступны внешние сети")
        networks[key] = {
            "name": f"{name}-{key}",
            "labels": {"tracker.test_run": str(run_id)},
        }
    if config.get("configs") or config.get("secrets"):
        raise ValidationError("Для тестов передайте настройки через environment и env_file")
    for service_name, service in config["services"].items():
        allowed = {
            "image",
            "build",
            "command",
            "entrypoint",
            "environment",
            "env_file",
            "healthcheck",
            "volumes",
            "networks",
            "depends_on",
            "working_dir",
            "user",
            "init",
            "read_only",
            "tmpfs",
            "labels",
            "ports",
            "container_name",
            "restart",
            "profiles",
            "deploy",
            "pull_policy",
            "platform",
            "hostname",
            "domainname",
            "stop_grace_period",
            "stop_signal",
            "logging",
            "tty",
            "stdin_open",
            "mem_limit",
            "mem_reservation",
            "mem_swappiness",
            "memswap_limit",
            "cpus",
            "cpu_count",
            "cpu_percent",
            "cpu_shares",
            "cpu_period",
            "cpu_quota",
            "cpu_rt_runtime",
            "cpu_rt_period",
            "cpuset",
            "shm_size",
            "cap_drop",
            "ulimits",
            "pids_limit",
            "dns",
            "dns_search",
            "dns_opt",
            "extra_hosts",
            "expose",
            "attach",
            "annotations",
            "scale",
            "develop",
        }
        unsupported = set(service) - allowed
        if unsupported:
            raise ValidationError(
                "Профиль содержит неподдерживаемые параметры: " + ", ".join(sorted(unsupported)),
            )
        if service.get("deploy", {}).get("resources", {}).get("reservations", {}).get("devices"):
            raise ValidationError("Профиль тестов не поддерживает устройства хоста")
        for field in ("container_name", "ports", "restart", "profiles"):
            service.pop(field, None)
        deploy = service.get("deploy", {})
        service["deploy"] = {"resources": deploy["resources"]} if "resources" in deploy else {}
        for env_file in service.get("env_file", []):
            filename = env_file["path"] if isinstance(env_file, dict) else env_file
            if not Path(filename).resolve().is_relative_to(snapshot.resolve()):
                raise ValidationError("Файл окружения должен находиться внутри снимка")
        service["restart"] = "no"
        image = service.get("image", "").split("/")[-1].split(":")[0]
        checks = {
            "postgres": ["CMD-SHELL", 'pg_isready -U "$${POSTGRES_USER:-postgres}"'],
            "mysql": ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "--silent"],
            "redis": ["CMD", "redis-cli", "ping"],
        }
        if image in checks and "healthcheck" not in service:
            service["healthcheck"] = {
                "test": checks[image],
                "interval": "2s",
                "timeout": "5s",
                "retries": DEPENDENCY_HEALTH_RETRIES,
            }
        service["labels"] = {
            **service.get("labels", {}),
            "tracker.test_run": str(run_id),
        }
        if service.get("build"):
            build = service["build"]
            if isinstance(build, str):
                build = {"context": build}
                service["build"] = build
            context = Path(build.get("context", snapshot)).resolve()
            if not context.is_relative_to(snapshot.resolve()):
                raise ValidationError("Контекст сборки должен находиться внутри репозитория")
            dockerfile = Path(build.get("dockerfile", "Dockerfile"))
            if not (context / dockerfile).resolve().is_relative_to(snapshot.resolve()):
                raise ValidationError("Dockerfile должен находиться внутри снимка")
            if (
                build.get("ssh")
                or build.get("secrets")
                or build.get("entitlements")
                or build.get("privileged")
                or build.get("network") not in (None, "default")
            ):
                raise ValidationError("Сборка тестов не поддерживает доступы хоста")
            for additional in build.get("additional_contexts", {}).values():
                if not Path(additional).resolve().is_relative_to(snapshot.resolve()):
                    raise ValidationError("Контекст сборки должен находиться внутри снимка")
            service["image"] = f"{name}-{service_name}:latest"
        mounts = []
        for index, entry in enumerate(service.get("volumes", [])):
            entry = dict(entry)
            if entry["type"] != "bind":
                mounts.append(entry)
                continue
            source = Path(entry["source"]).resolve()
            if not source.is_relative_to(snapshot.resolve()):
                raise ValidationError("Монтировать можно только файлы снимка репозитория")
            if not source.exists():
                source.mkdir(parents=True, exist_ok=True)
            if mount is not None and mount.type == "volume" and source.is_dir():
                key = f"source-{service_name}-{index}"
                volumes[key] = {"external": True, "name": mount.name}
                entry = {
                    "type": "volume",
                    "source": key,
                    "target": entry["target"],
                    "read_only": entry.get("read_only", False),
                    "volume": {
                        "subpath": source.relative_to(resolve_repos_root().resolve()).as_posix(),
                        "nocopy": True,
                    },
                }
            elif mount is not None:
                entry["source"] = str(
                    Path(mount.source) / source.relative_to(resolve_repos_root().resolve()),
                )
            mounts.append(entry)
        service["volumes"] = mounts
    return {
        "name": name,
        "services": config["services"],
        "volumes": volumes,
        "networks": networks,
    }


async def prepare(executor: ComposeExecutor) -> None:
    run = executor.run
    profile = TestProfile.model_validate(run.profile)
    snapshot = executor.directory / "source"
    source = executor.directory.parent.parent / run.repository_name
    if not (source / ".git").exists():
        async with redis_connection() as redis:
            async with wait_for_lock(
                redis,
                lock_key(run.task_id, "test-workspace"),
                ttl_seconds=WORKSPACE_LOCK_SECONDS,
                wait_seconds=WORKSPACE_WAIT_SECONDS,
            ) as acquired:
                if not acquired:
                    raise ConflictError("Подготовка рабочей копии занята другим прогоном")
                async with async_session_factory() as db:
                    task = await db.get(Task, run.task_id)
                    assert task is not None
                    await prepare_task_workspace(db, task=task, repos_root=resolve_repos_root())
    copying = asyncio.create_task(asyncio.to_thread(snapshot_repository, source, snapshot))
    try:
        await asyncio.shield(copying)
    except asyncio.CancelledError:
        # Поток копирования должен закончить запись до удаления снимка.
        await copying
        raise
    example = inside(snapshot, ".env.example")
    env_file = snapshot / ".env"
    variables = "\n".join(
        key + "='" + value.replace("'", "\\'") + "'" for key, value in profile.environment.items()
    )
    env_file.touch(mode=0o600)
    env_file.write_text((example.read_text() if example.is_file() else "") + "\n" + variables)

    args = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--project-name",
        project_name(run.id),
    ]
    for filename in profile.compose_files:
        file = inside(snapshot, filename)
        if not file.is_file():
            raise ValidationError(f"Compose-файл {filename} отсутствует")
        args.extend(["--file", str(file)])
    args.extend(["config", "--format", "json"])
    # Разбор Compose читает env_file/include до нашей проверки. Выполняем
    # его в контейнере, которому доступен только снимок репозитория.
    args = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        f"--memory={COMPOSE_RENDER_MEMORY}",
        f"--cpus={COMPOSE_RENDER_CPUS}",
        "--label",
        f"tracker.test_run={run.id}",
        *await mount_args(snapshot, resolve_repos_root()),
        "-w",
        str(snapshot),
        COMPOSE_RENDER_IMAGE,
        *args,
    ]
    config = json.loads(await executor.command(args, capture=True))
    if profile.service not in config.get("services", {}):
        raise ValidationError("Сервис выполнения отсутствует в Compose")
    config = await isolated_config(config, snapshot=snapshot, run_id=run.id)
    if profile.working_directory:
        config["services"][profile.service]["working_dir"] = profile.working_directory
    for service in config["services"].values():
        service["environment"] = {
            **service.get("environment", {}),
            **{key: value.replace("$", "$$") for key, value in profile.environment.items()},
        }
    manifest = executor.directory / "compose.json"
    manifest.touch(mode=0o600)
    # config уже интерполирован. Защищаем литералы $ при втором чтении Compose.
    manifest.write_text(json.dumps(config))
    await executor.command(executor.compose("build", profile.service))
    dependencies = list(config["services"][profile.service].get("depends_on", {}))
    if dependencies:
        await executor.command(
            executor.compose(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                str(DEPENDENCY_WAIT_SECONDS),
                *dependencies,
            )
        )


async def docker_command(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), DOCKER_COMMAND_TIMEOUT_SECONDS
        )
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace")[-2000:])
    return stdout.decode().strip()


async def cleanup_run(run_id: uuid.UUID, *, include_agent: bool = True) -> None:
    async with redis_connection() as redis:
        try:
            async with acquire_task_operation_lock(
                redis,
                task_id=run_id,
                operation="test-cleanup",
                ttl_seconds=CLEANUP_LOCK_SECONDS,
            ):
                await _cleanup_run(run_id, include_agent=include_agent)
        except LockNotAcquiredError:
            # Другой исполнитель уже очищает тот же прогон.
            return


async def _cleanup_run(run_id: uuid.UUID, *, include_agent: bool) -> None:
    async with async_session_factory() as db:
        run = await db.get(TestRun, run_id)
        if run is None:
            return
        task = await db.get(Task, run.task_id)
        assert task is not None
        directory = run_directory(task, run.id)
        if run.status in ACTIVE_STATUSES:
            raise ConflictError("Сначала остановите выполняющийся прогон")
    await update_run(run_id, cleanup_status="running", cleanup_error=None)
    try:
        if run.cleanup_error and run.cleanup_error.startswith("Не удалось сохранить отчёты"):
            reports = await save_reports(run, task, directory)
            await update_run(run_id, report_files=reports)
        name = project_name(run_id)
        selector = f"label=com.docker.compose.project={name}"
        # Ресурсы ищутся по проекту даже при сбое до записи compose.json.
        containers = list(
            set(
                (await docker_command("ps", "-aq", "--filter", selector)).split()
                + (
                    await docker_command(
                        "ps",
                        "-aq",
                        "--filter",
                        f"label=tracker.test_run={run_id}",
                    )
                ).split()
            )
        )
        if include_agent:
            containers += (
                await docker_command(
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=tracker.test_agent={run_id}",
                )
            ).split()
        if containers:
            await docker_command("rm", "-f", "-v", *containers)
        networks = (await docker_command("network", "ls", "-q", "--filter", selector)).split()
        if networks:
            await docker_command("network", "rm", *networks)
        volumes = (await docker_command("volume", "ls", "-q", "--filter", selector)).split()
        if volumes:
            await docker_command("volume", "rm", *volumes)
        images = (
            await docker_command(
                "image",
                "ls",
                "--format",
                "{{.Repository}}:{{.Tag}}",
                "--filter",
                f"reference={name}-*",
            )
        ).split()
        if images:
            await docker_command("image", "rm", *images)
        if include_agent:
            async with redis_connection() as redis:
                await redis.delete(
                    gate_key(run_id), request_key(run_id), reservation_key(task.created_by, run_id)
                )
            agent_directory = resolve_sessions_root() / task.code / "test-agents" / str(run_id)
            if agent_directory.exists():
                await asyncio.to_thread(shutil.rmtree, agent_directory)
        if directory.exists():
            await asyncio.to_thread(shutil.rmtree, directory)
        await update_run(
            run_id,
            cleanup_status="done" if include_agent or run.source != "ci-agent" else "pending",
        )
    except (RuntimeError, OSError, TimeoutError, ValidationError) as exc:
        await update_run(
            run_id,
            cleanup_status="failed",
            cleanup_error=(
                run.cleanup_error
                if run.cleanup_error and run.cleanup_error.startswith("Не удалось сохранить отчёты")
                else str(exc)
            ),
        )
        raise


async def save_reports(
    run: TestRun,
    task: Task,
    directory: Path,
    *,
    container_expected: bool = True,
) -> list[str]:
    reports: list[str] = []
    artifacts = task_artifacts_dir(task.code) / "test-runs" / str(run.id)
    for relative in run.profile.get("report_paths", []):
        source = inside(directory / "source", relative)
        destination = inside(artifacts, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            await asyncio.to_thread(shutil.copy2, source, destination)
        else:
            container = f"{project_name(run.id)}-run"
            try:
                workdir = await docker_command(
                    "inspect",
                    "--format",
                    "{{.Config.WorkingDir}}",
                    container,
                )
                path = f"{workdir or '/'}/{relative}"
                await docker_command("cp", f"{container}:{path}", str(destination))
            except RuntimeError as exc:
                message = str(exc).lower()
                if "could not find the file" in message:
                    continue
                if not container_expected and (
                    "no such object" in message or "no such container" in message
                ):
                    continue
                raise OSError(f"Не удалось выгрузить отчёт {relative}: {exc}") from exc
        reports.append(f"test-runs/{run.id}/{relative}")
    return reports


async def execute_run(run_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        claimed = await db.execute(
            sa.update(TestRun)
            .where(
                TestRun.id == run_id,
                TestRun.status.in_(("queued", "agent")),
            )
            .values(
                status="preparing",
                started_at=datetime.now(UTC),
                heartbeat_at=datetime.now(UTC),
            )
            .returning(TestRun)
        )
        run = claimed.scalar_one_or_none()
        await db.commit()
        if run is None:
            return
        task = await db.get(Task, run.task_id)
        assert task is not None
        directory = run_directory(task, run.id)
    directory.mkdir(parents=True, exist_ok=True)
    executor = ComposeExecutor(run, directory)

    async def heartbeat() -> None:
        while True:
            await update_run(run_id, heartbeat_at=datetime.now(UTC))
            await asyncio.sleep(RUN_HEARTBEAT_SECONDS)

    pulse = asyncio.create_task(heartbeat())
    executing = False
    status, exit_code, error = "failed", None, None
    try:
        async with asyncio.timeout(run.profile["timeout_seconds"]):
            if await cancelled(run_id):
                raise RunCancelled
            await prepare(executor)
            await update_run(run_id, status="running")
            executing = True
            command = run.profile["commands"][run.check]
            await executor.command(
                executor.compose(
                    "run",
                    "--name",
                    f"{project_name(run_id)}-run",
                    "--no-deps",
                    "-T",
                    run.profile["service"],
                    "sh",
                    "-lc",
                    command,
                )
            )
            status, exit_code = "passed", 0
    except RunCancelled:
        status = "cancelled"
    except TimeoutError:
        status, error = "timed_out", "Проверка превысила таймаут"
    except ComposeFailed as exc:
        exit_code = exc.exit_code
        error = f"Проверка завершилась с кодом {exc.exit_code}" if executing else str(exc)
    except Exception as exc:
        error = str(exc)
    finally:
        pulse.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pulse
        try:
            reports = await save_reports(run, task, directory, container_expected=executing)
        except (OSError, ValidationError, TimeoutError) as exc:
            await update_run(
                run_id,
                status="failed",
                exit_code=exit_code,
                error=str(exc),
                finished_at=datetime.now(UTC),
                cleanup_status="failed",
                cleanup_error="Не удалось сохранить отчёты. Повторите очистку.",
            )
            return
        await update_run(
            run_id,
            status=status,
            exit_code=exit_code,
            error=redact(error, run.profile.get("environment", {})) if error else None,
            finished_at=datetime.now(UTC),
            report_files=reports,
        )
        with contextlib.suppress(RuntimeError, OSError, TimeoutError):
            await cleanup_run(run_id, include_agent=run.source != "ci-agent")


async def recover_runs() -> None:
    """
    Повторная доставка очереди и уборка прогонов, переживших свой воркер.
    """
    from tasks.test_runs import cleanup_test_run, execute_test_run

    threshold = datetime.now(UTC) - timedelta(seconds=STALE_SECONDS)
    async with async_session_factory() as db:
        runs = list(
            (
                await db.scalars(
                    sa.select(TestRun).where(
                        sa.or_(
                            TestRun.status.in_(ACTIVE_STATUSES),
                            TestRun.cleanup_status.in_(("pending", "failed", "running")),
                        )
                    )
                )
            ).all()
        )
    # Проверяем также ресурсы завершённых прогонов: запрос Docker мог
    # завершиться на демоне уже после аварийного выхода клиента.
    resources: set[uuid.UUID] = set()
    for kind, listing in (
        ("container", ["ps", "-aq"]),
        ("network", ["network", "ls", "-q"]),
        ("volume", ["volume", "ls", "-q"]),
    ):
        identifiers = (
            await docker_command(
                *listing,
                "--filter",
                "label=tracker.test_run",
            )
        ).split()
        if kind == "container":
            identifiers += (
                await docker_command(
                    *listing,
                    "--filter",
                    "label=tracker.test_agent",
                )
            ).split()
        if not identifiers:
            continue
        details = []
        for identifier in set(identifiers):
            try:
                details.extend(
                    json.loads(await docker_command("inspect", "--type", kind, identifier))
                )
            except RuntimeError:
                # Ресурс мог удалить параллельный исполнитель очистки.
                continue
        for item in details:
            labels = item.get("Config", {}).get("Labels") or item.get("Labels") or {}
            value = labels.get("tracker.test_run") or labels.get("tracker.test_agent", "")
            with contextlib.suppress(ValueError):
                resources.add(uuid.UUID(value))
    images = await docker_command(
        "image",
        "ls",
        "--format",
        "{{.Repository}}",
        "--filter",
        "reference=tracker-check-*",
    )
    for image in images.split():
        with contextlib.suppress(ValueError):
            resources.add(uuid.UUID(image.removeprefix("tracker-check-")[:32]))
    known = {run.id for run in runs}
    if resources - known:
        async with async_session_factory() as db:
            runs += list(
                (
                    await db.scalars(
                        sa.select(TestRun).where(
                            TestRun.id.in_(resources - known),
                            TestRun.cleanup_status == "done",
                        )
                    )
                ).all()
            )
    for run in runs:
        if run.status == "queued":
            execute_test_run.delay(str(run.id))
        elif run.status in ACTIVE_STATUSES:
            if run.heartbeat_at is not None and run.heartbeat_at >= threshold:
                continue
            async with async_session_factory() as db:
                changed = await db.execute(
                    sa.update(TestRun)
                    .where(
                        TestRun.id == run.id,
                        TestRun.status.in_(ACTIVE_STATUSES),
                        sa.or_(TestRun.heartbeat_at < threshold, TestRun.heartbeat_at.is_(None)),
                    )
                    .values(
                        status="failed",
                        error="Воркер прогона потерял связь",
                        finished_at=datetime.now(UTC),
                    )
                    .returning(TestRun.id)
                )
                stale = changed.scalar_one_or_none()
                await db.commit()
            if stale is not None:
                cleanup_test_run.delay(str(run.id))
        elif run.cleanup_status != "done" or run.id in resources:
            if (
                run.source == "ci-agent"
                and run.heartbeat_at is not None
                and run.heartbeat_at >= threshold
            ):
                continue
            cleanup_test_run.delay(str(run.id))


async def cancel_task_runs(db: AsyncSession, task_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(TestRun)
        .where(
            TestRun.task_id == task_id,
            TestRun.status.in_(ACTIVE_STATUSES),
        )
        .values(cancel_requested=True)
    )
    await db.commit()


async def execute_node_check(
    *,
    db: AsyncSession,
    node: Node,
    node_log_id: uuid.UUID,
) -> tuple[bool, str, int | None, str | None]:
    from tasks.test_runs import execute_test_run

    if node.test_repository_id is None or node.test_check is None:
        raise ValidationError("Для проверки выберите репозиторий и команду")
    log = await db.get(NodeLog, node_log_id)
    if log is None:
        raise NotFoundError("Запись выполнения ноды не найдена")
    task = await db.get(Task, log.task_id)
    assert task is not None
    run = await create_run(
        db,
        task=task,
        repository_id=node.test_repository_id,
        check=node.test_check,
        source="node",
        idempotency_key=node_log_id,
    )
    execute_test_run.delay(str(run.id))
    try:
        while True:
            async with async_session_factory() as read_db:
                current = await read_db.get(TestRun, run.id)
            assert current is not None
            if current.status not in ACTIVE_STATUSES and current.cleanup_status in (
                "done",
                "failed",
            ):
                success = current.status == "passed" and current.cleanup_status == "done"
                return (
                    success,
                    current.logs,
                    current.exit_code,
                    current.error or current.cleanup_error,
                )
            await asyncio.sleep(POLL_SECONDS)
    except asyncio.CancelledError:
        await update_run(run.id, cancel_requested=True)
        raise
