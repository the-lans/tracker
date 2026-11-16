"""Настройки TWG и окружение только для сессий автора задачи."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.twg import TwgConnection
from db.models.users import User
from services.crypto import decrypt, encrypt
from services.errors import ValidationError

TWG_PLUGIN_PATH = "/opt/tracker-twg"


@dataclass(frozen=True, slots=True)
class TwgConnectionStatus:
    enabled: bool
    configured: bool
    site: str | None = None
    email: str | None = None


def twg_enabled() -> bool:
    return os.environ.get("TRACKER_TWG_ENABLED", "true").lower() in {"true", "1", "yes"}


def normalize_site(site: str) -> str:
    if any(c.isspace() for c in site):
        raise ValidationError("Адрес сайта не должен содержать пробелы")
    try:
        parsed = urlsplit(site if "://" in site else "https://" + site)
    except ValueError as exc:
        raise ValidationError("Некорректный адрес сайта Atlassian") from exc
    host = parsed.netloc.lower()
    if (
        parsed.scheme != "https"
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.atlassian\.net", host)
    ):
        raise ValidationError("Укажите сайт Atlassian Cloud вида company.atlassian.net")
    return host


async def connection_status(db: AsyncSession, user_id: uuid.UUID) -> TwgConnectionStatus:
    row = await db.get(TwgConnection, user_id)
    return TwgConnectionStatus(
        enabled=twg_enabled(),
        configured=row is not None,
        site=row.site if row else None,
        email=row.email if row else None,
    )


async def save_connection(
    db: AsyncSession, *, user_id: uuid.UUID, site: str, email: str, token: str | None
) -> TwgConnectionStatus:
    site = normalize_site(site.strip())
    email = email.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValidationError("Укажите email учётной записи Atlassian")
    # Строка пользователя сериализует и первое сохранение подключения.
    await db.get(User, user_id, with_for_update=True)
    row = await db.get(TwgConnection, user_id, with_for_update=True)
    if token is not None and (not token.strip() or any(c.isspace() for c in token)):
        raise ValidationError("Токен не должен быть пустым или содержать пробелы")
    if row is None:
        if token is None:
            raise ValidationError("Для подключения TWG нужен личный токен Atlassian")
        row = TwgConnection(user_id=user_id, site=site, email=email, token_encrypted=encrypt(token))
        db.add(row)
    else:
        if token is None and (row.site != site or row.email != email):
            raise ValidationError("При смене сайта или email введите токен заново")
        row.site, row.email = site, email
        if token is not None:
            row.token_encrypted = encrypt(token)
    await db.commit()
    return await connection_status(db, user_id)


async def delete_connection(db: AsyncSession, user_id: uuid.UUID) -> TwgConnectionStatus:
    await db.get(User, user_id, with_for_update=True)
    row = await db.get(TwgConnection, user_id, with_for_update=True)
    if row is not None:
        await db.delete(row)
    await db.commit()
    return await connection_status(db, user_id)


async def session_environment(db: AsyncSession, user_id: uuid.UUID) -> dict[str, str]:
    if not twg_enabled():
        return {}
    row = await db.get(TwgConnection, user_id, populate_existing=True)
    if row is None:
        return {}
    return {"TWG_USER": row.email, "TWG_SITE": row.site, "TWG_TOKEN": decrypt(row.token_encrypted)}
