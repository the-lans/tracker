"""Первичное заполнение `allowed_emails` email'ом первого администратора
(раздел 19.1, 20.2 ТЗ).

Без этого шага вход в систему невозможен ни для кого вообще: регистрация
НОВОГО пользователя (в т.ч. самого первого — раздел 19.1 не делает для него
исключения) требует присутствия его email в `allowed_emails` уже ДО первого
входа через Google OAuth — курица и яйцо, которое разрывает только этот
скрипт, запускаемый `deploy/install.sh` на шаге генерации окружения, когда
в БД ещё нет ни одного пользователя.

Запуск:

    backend/.venv/bin/python scripts/seed_admin_allowlist.py admin@example.com

Идемпотентен: повторный запуск с тем же email не создаёт дубликат
(`allowed_emails.email` уникален).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import sqlalchemy as sa  # noqa: E402

from app_logging.config import configure_logging, get_logger  # noqa: E402
from db.models.users import AllowedEmail  # noqa: E402
from db.session import async_session_factory  # noqa: E402

configure_logging()
logger = get_logger("seed_admin_allowlist")


async def _seed(email: str) -> None:
    async with async_session_factory() as db_session:
        existing = await db_session.scalar(
            sa.select(AllowedEmail).where(AllowedEmail.email == email),
        )
        if existing is not None:
            logger.info("admin_allowlist_already_seeded", email=email)
            return
        db_session.add(AllowedEmail(email=email))
        await db_session.commit()
        logger.info("admin_allowlist_seeded", email=email)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Использование: seed_admin_allowlist.py <email>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(_seed(sys.argv[1]))
