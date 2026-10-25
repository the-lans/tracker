"""
Локальные git-репозитории для тестов: bare-origin вместо GitLab (раздел 21.1
ТЗ) и коммиты от имени тестового автора.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_AUTHOR_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def run(*args: str, cwd: Path, check: bool = True) -> str:
    result = subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)
    return result.stdout


def commit_file(repo_dir: Path, filename: str, content: str, *, message: str) -> None:
    (repo_dir / filename).write_text(content)
    run("git", "add", filename, cwd=repo_dir)
    run("git", *GIT_AUTHOR_ARGS, "commit", "-m", message, cwd=repo_dir)


def init_bare_origin(tmp_path: Path, name: str = "origin") -> Path:
    """Bare-репозиторий с веткой `main` и одним коммитом (`README.md`)."""
    origin = tmp_path / f"{name}.git"
    run("git", "init", "--bare", "--initial-branch=main", str(origin), cwd=tmp_path)
    seed_dir = tmp_path / f"{name}-seed"
    run("git", "clone", str(origin), str(seed_dir), cwd=tmp_path)
    run("git", "checkout", "-B", "main", cwd=seed_dir)
    commit_file(seed_dir, "README.md", "исходный файл\n", message="начальный коммит")
    run("git", "push", "origin", "main", cwd=seed_dir)
    return origin


def push_base_update(tmp_path: Path, origin: Path, filename: str, content: str) -> None:
    """Кто-то другой обновляет `main` в origin."""
    updater_dir = tmp_path / f"updater-{filename}"
    run("git", "clone", str(origin), str(updater_dir), cwd=tmp_path)
    commit_file(updater_dir, filename, content, message="апдейт базовой ветки")
    run("git", "push", "origin", "main", cwd=updater_dir)
