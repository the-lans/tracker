"""Контракт тестового окружения, общий для API и исполнителя."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_TEST_TIMEOUT_SECONDS = 900
MIN_TEST_TIMEOUT_SECONDS = 10
MAX_TEST_TIMEOUT_SECONDS = 7200


class TestProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compose_files: list[str] = Field(default_factory=lambda: ["compose.yml"], min_length=1)
    service: str = Field(default="app", min_length=1)
    working_directory: str | None = None
    commands: dict[str, str] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(
        default=DEFAULT_TEST_TIMEOUT_SECONDS,
        ge=MIN_TEST_TIMEOUT_SECONDS,
        le=MAX_TEST_TIMEOUT_SECONDS,
    )
    report_paths: list[str] = Field(default_factory=list)

    @field_validator("compose_files", "report_paths")
    @classmethod
    def relative_paths(cls, paths: list[str]) -> list[str]:
        for value in paths:
            path = PurePosixPath(value)
            if not value or path.is_absolute() or ".." in path.parts:
                raise ValueError("Укажите относительный путь внутри репозитория")
        return paths

    @field_validator("commands")
    @classmethod
    def command_names(cls, commands: dict[str, str]) -> dict[str, str]:
        for name, command in commands.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or not command.strip():
                raise ValueError("Укажите имя проверки латиницей и непустую команду")
        return commands

    @field_validator("environment")
    @classmethod
    def environment_names(cls, environment: dict[str, str]) -> dict[str, str]:
        for name, value in environment.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or "\0" in value:
                raise ValueError("Укажите допустимое имя и значение переменной окружения")
        return environment
