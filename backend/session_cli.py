#!/usr/bin/env python3
"""
Обёртка ``cli_path`` Claude Agent SDK (раздел 19.3 ТЗ, решение №22 плана):
запускает Claude Code CLI в одноразовом контейнере сессии, а не в контейнере
воркера.

SDK вызывает её так же, как сам CLI, — с аргументами CLI и окружением
воркера плюс `ClaudeAgentOptions.env`. Аргументы `docker run` (монтирование,
лимиты, сеть) собирает воркер (`services/session_container.py`) и передаёт
JSON в `TRACKER_SESSION_DOCKER_SPEC`. В контейнер переходят только
переменные из белого списка — по имени (`-e NAME`), значение берёт клиент
Docker из окружения обёртки, в командную строку оно не попадает.

Только стандартная библиотека: модуль запускается как отдельная программа.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from typing import NoReturn

DOCKER_SPEC_ENV = "TRACKER_SESSION_DOCKER_SPEC"
_FORWARDED_PREFIXES = ("CLAUDE_", "ANTHROPIC_")
_FORWARDED_NAMES = frozenset(
    {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"},
)
_CLI_COMMAND = "claude"
_USAGE_EXIT_CODE = 2


def forwarded_env_names(environ: Mapping[str, str]) -> list[str]:
    """Настройки CLI и SDK и прокси; секреты сервера под эти имена не попадают."""
    return sorted(
        name
        for name in environ
        if name.startswith(_FORWARDED_PREFIXES) or name in _FORWARDED_NAMES
    )


def build_command(argv: Sequence[str], environ: Mapping[str, str]) -> list[str]:
    spec = json.loads(environ[DOCKER_SPEC_ENV])
    command = [
        "docker",
        "run",
        "-i",
        "--rm",
        "--name",
        f"{spec['name_prefix']}{uuid.uuid4().hex[:12]}",
        *spec["docker_args"],
    ]
    for name in forwarded_env_names(environ):
        command += ["-e", name]
    return [*command, spec["image"], _CLI_COMMAND, *argv]


def main() -> NoReturn:
    if DOCKER_SPEC_ENV not in os.environ:
        print(
            f"{DOCKER_SPEC_ENV} не задана: обёртку запускает воркер сессий трекера",
            file=sys.stderr,
        )
        sys.exit(_USAGE_EXIT_CODE)
    command = build_command(sys.argv[1:], os.environ)
    os.execvp(command[0], command)  # noqa: S606 — замена процесса на `docker run`


if __name__ == "__main__":
    main()
