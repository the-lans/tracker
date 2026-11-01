"""Перенос истории сессий задач из каталогов прежних LLM-аккаунтов (раздел 20.6 ТЗ).

Запуск — из `deploy/install.sh --update` после миграций БД:

    docker compose run --rm backend python /app/scripts/migrate_claude_sessions.py

Идемпотентен: уже перенесённые файлы не перезаписываются
(`services/session_history_migration.py`).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app_logging.config import configure_logging  # noqa: E402
from db.session import async_session_factory  # noqa: E402
from services.session_history_migration import (  # noqa: E402
    migrate_session_histories,
    resolve_accounts_root,
)


async def main() -> None:
    configure_logging()
    async with async_session_factory() as db_session:
        await migrate_session_histories(db_session, accounts_root=resolve_accounts_root())


if __name__ == "__main__":
    asyncio.run(main())
