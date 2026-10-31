"""Запуск alembic на отдельной временной базе — для тестов миграций."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_alembic(database_url: str, *args: str) -> None:
    """``alembic <args>`` тем же venv, что и pytest, на базе ``database_url``."""
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_BACKEND_DIR,
        check=True,
        capture_output=True,
        env={**os.environ, "DATABASE_URL": database_url},
    )
