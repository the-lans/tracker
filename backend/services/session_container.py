"""
Контейнер сессии — окружение процесса Claude Code CLI задачи (раздел 6.1,
19.3 ТЗ, решение №22 плана).

SDK запускает CLI через ``cli_path``: вместо самого CLI это обёртка
`session_cli.py`, которая выполняет ``docker run -i --rm`` образа
`tracker-session` с аргументами, собранными здесь. Обмен с CLI идёт через
stdin/stdout контейнера — `ClaudeSDKClient`, callback разрешений, БД и git
остаются в воркере.

В контейнер монтируются только каталоги задачи (репозитории, артефакты) и
конфигурационная директория её сессии — по тем же путям, что в воркере, так
что история сессии и пути в ответах агента совпадают
(`services/docker_mounts.py`). Переменные окружения обёртка передаёт по
белому списку — секреты воркера в контейнер не попадают.

К модели CLI обращается только через `llm-gateway` (раздел 19.7): адрес шлюза
и токен сессии — в `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`, а контейнер
подключён к сети `llm_sessions`, где кроме контейнеров сессий есть только шлюз.
Сеть одна: Docker не подключает контейнер к стандартной `bridge` вместе с
пользовательской сетью, поэтому выход наружу (MCP-серверы) даёт сама
`llm_sessions`.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from services.claude_config import resolve_sessions_root
from services.docker_mounts import mount_args
from services.git_ops import AGENT_GIT_IDENTITY
from services.task_artifacts import resolve_user_files_root
from services.task_workspace import resolve_repos_root

SESSION_CLI_PATH = Path(__file__).resolve().parent.parent / "session_cli.py"
# Читает обёртка `session_cli.py`: JSON с префиксом имени контейнера,
# аргументами `docker run` и образом.
SESSION_DOCKER_SPEC_ENV = "TRACKER_SESSION_DOCKER_SPEC"
SESSION_IMAGE_ENV = "TRACKER_SESSION_IMAGE"
DEFAULT_SESSION_IMAGE = "tracker-session:latest"
# Сеть без `llm_sessions` (разработка без compose) — внешняя `bridge` Docker,
# не сеть сервисов compose: Postgres, Redis и backend из контейнера недоступны
# (раздел 19.3).
SESSION_NETWORK_ENV = "TRACKER_SESSION_NETWORK"
DEFAULT_SESSION_NETWORK = "bridge"
# Сеть `llm_sessions` с шлюзом (docker-compose.yml): в ней только контейнеры
# сессий и llm-gateway; пустое значение — без неё.
SESSION_LLM_NETWORK_ENV = "TRACKER_SESSION_LLM_NETWORK"
DEFAULT_SESSION_LLM_NETWORK = "tracker-llm-sessions"
LLM_GATEWAY_URL_ENV = "LLM_GATEWAY_URL"
DEFAULT_LLM_GATEWAY_URL = "http://llm-gateway:8320"
# По метке `purge_orphaned_session_containers` находит контейнеры сессий,
# пережившие свой воркер (раздел 16.2).
SESSION_TASK_LABEL = "tracker.task"
SESSION_CONTAINER_PREFIX = "tracker-session-"
# Раздел 19.3 требует лимиты, не называя значений: агент собирает и
# тестирует проекты, поэтому щедрее, чем у script-нод.
_MEMORY_LIMIT = "4g"
_CPU_LIMIT = "2.0"
# Пользователю воркера в контейнере может не найтись записи в /etc/passwd,
# а CLI пишет в домашний каталог.
_CONTAINER_HOME = "/tmp"


def _network_args() -> list[str]:
    llm_network = os.environ.get(SESSION_LLM_NETWORK_ENV, DEFAULT_SESSION_LLM_NETWORK)
    network = llm_network or os.environ.get(SESSION_NETWORK_ENV, DEFAULT_SESSION_NETWORK)
    return ["--network", network]


def _isolation_args(task_id: uuid.UUID) -> list[str]:
    """Метка задачи, пользователь воркера, сети, лимиты и урезанные привилегии."""
    return [
        "--label",
        f"{SESSION_TASK_LABEL}={task_id}",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        *_network_args(),
        f"--memory={_MEMORY_LIMIT}",
        f"--cpus={_CPU_LIMIT}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        _CONTAINER_HOME,
        "-e",
        f"HOME={_CONTAINER_HOME}",
        *_git_identity_args(),
    ]


def _git_identity_args() -> list[str]:
    """Агент коммитит в рабочую ветку, а git-конфига в контейнере нет."""
    args: list[str] = []
    for name, value in AGENT_GIT_IDENTITY.items():
        args += ["-e", f"{name}={value}"]
    return args


async def _task_mount_args(
    *,
    cwd: Path,
    config_dir: Path,
    artifacts_dir: Path | None,
) -> list[str]:
    args = await mount_args(cwd, resolve_repos_root())
    if artifacts_dir is not None:
        args += await mount_args(artifacts_dir, resolve_user_files_root())
    args += await mount_args(config_dir, resolve_sessions_root())
    return args


async def build_session_cli_env(
    *,
    task_id: uuid.UUID,
    cwd: Path,
    config_dir: Path,
    session_token: str,
    artifacts_dir: Path | None = None,
) -> dict[str, str]:
    """
    Окружение обёртки для сессии задачи `task_id` — добавляется к
    `ClaudeAgentOptions.env`. `cwd` — каталог репозиториев задачи,
    ``config_dir`` — конфигурационная директория сессии (раздел 6.4),
    ``session_token`` — токен сессии для шлюза, ``artifacts_dir`` — каталог
    артефактов, если он нужен сессии.
    """
    docker_args = [
        *_isolation_args(task_id),
        *await _task_mount_args(cwd=cwd, config_dir=config_dir, artifacts_dir=artifacts_dir),
        "-w",
        str(cwd),
    ]
    spec = {
        "name_prefix": f"{SESSION_CONTAINER_PREFIX}{task_id}-",
        "docker_args": docker_args,
        "image": os.environ.get(SESSION_IMAGE_ENV, DEFAULT_SESSION_IMAGE),
    }
    return {
        SESSION_DOCKER_SPEC_ENV: json.dumps(spec),
        "ANTHROPIC_BASE_URL": os.environ.get(LLM_GATEWAY_URL_ENV, DEFAULT_LLM_GATEWAY_URL),
        "ANTHROPIC_AUTH_TOKEN": session_token,
    }
