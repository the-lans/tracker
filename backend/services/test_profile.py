"""Определение настроек проверок по файлам репозитория."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import yaml

from db.models.repositories import Repository
from services.errors import ValidationError
from services.git_ops import _deploy_key_env, _run_git
from services.repository_validation import validate_branch_name, validate_git_url
from services.test_profile_types import TestProfile

PROFILE_CLONE_TIMEOUT_SECONDS = 120


def detect_directory(root: Path) -> TestProfile:
    filenames = [
        name
        for name in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")
        if (root / name).is_file()
    ]
    if not filenames:
        raise ValidationError("В корне репозитория не найден Compose-файл")
    try:
        data: Any = yaml.safe_load((root / filenames[0]).read_text()) or {}
    except yaml.YAMLError as exc:
        raise ValidationError("Compose-файл содержит ошибку YAML") from exc
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        raise ValidationError("Compose-файл должен содержать раздел services")
    services = data.get("services", {})
    preferred = ("app", "backend", "web", "api", "tests", "test", "runner")
    service = next((name for name in preferred if name in services), next(iter(services), None))
    if service is None:
        raise ValidationError("Compose-файл не содержит сервисов")
    commands = {}
    for name, file in (
        ("lint", "lint.sh"),
        ("unit", "unittests.sh"),
        ("integration", "integrationtests.sh"),
    ):
        if (root / "scripts" / file).is_file():
            commands[name] = f"sh /app/scripts/{file}"
    return TestProfile(compose_files=[filenames[0]], service=service, commands=commands)


async def detect_remote(
    *,
    repository: Repository,
    branch: str,
) -> TestProfile:
    validate_git_url(repository.git_url)
    validate_branch_name(branch)
    with tempfile.TemporaryDirectory(prefix="tracker-check-profile-") as temp:
        root = Path(temp)
        async with _deploy_key_env(repository) as environment:
            async with asyncio.timeout(PROFILE_CLONE_TIMEOUT_SECONDS):
                await _run_git(
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    branch,
                    "--",
                    repository.git_url,
                    str(root / "source"),
                    cwd=root,
                    env=environment,
                )
        return detect_directory(root / "source")
