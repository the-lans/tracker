"""Шлюзу не нужна конфигурация базы данных для запуска."""

import os
import subprocess
import sys


def test_gateway_import_without_database_url() -> None:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    subprocess.run(
        [sys.executable, "-c", "import llm_gateway.__main__"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
