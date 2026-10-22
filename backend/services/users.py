"""
Пользователи и доступ (раздел 15.1, 15.5, 16.2, 19.1 ТЗ, решения №16 и №18
плана): SSH-ключ профиля для SFTP-шлюза, блокировка пользователей, чей email
удалён из `allowed_emails`, и защита от потери последнего администратора.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.enums import AppLogLevel, UserRole
from db.models.logs import AppLog
from db.models.users import AllowedEmail, User
from services.errors import ConflictError
from services.ssh_keys import parse_public_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("users")

DEPROVISION_LOG_SOURCE = "periodic.deprovision_inactive_users"


async def set_ssh_public_key(db_session: AsyncSession, *, user: User, public_key: str) -> User:
    """Сохраняет ключ в нормализованном виде (`тип base64 [комментарий]`)."""
    user.ssh_public_key = parse_public_key(public_key).to_authorized_keys_line()
    # Раздел 16.2: давность использования считается заново для нового ключа.
    user.ssh_key_last_used_at = None
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def clear_ssh_public_key(db_session: AsyncSession, *, user: User) -> User:
    user.ssh_public_key = None
    user.ssh_key_last_used_at = None
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _active_admins_query() -> sa.Select[int]:
    return sa.select(sa.func.count()).where(
        User.role == UserRole.ADMIN,
        User.is_active == True,  # noqa: E712
    )


async def count_active_admins(db_session: AsyncSession) -> int:
    count: int = (await db_session.execute(_active_admins_query())).scalar_one()
    return count


async def _count_admins_keeping_access(db_session: AsyncSession, *, excluding_email: str) -> int:
    """Активные администраторы, чей email остаётся в `allowed_emails`."""
    stmt = _active_admins_query().where(
        User.email != excluding_email,
        sa.exists().where(AllowedEmail.email == User.email),
    )
    count: int = (await db_session.execute(stmt)).scalar_one()
    return count


async def _is_active_admin_email(db_session: AsyncSession, email: str) -> bool:
    stmt = sa.select(User.id).where(
        User.email == email,
        User.role == UserRole.ADMIN,
        User.is_active == True,  # noqa: E712
    )
    return (await db_session.scalar(stmt)) is not None


async def ensure_allowed_email_deletable(
    db_session: AsyncSession,
    allowed_email: AllowedEmail,
) -> None:
    """
    Удаление email из `allowed_emails` блокирует пользователя при ближайшем
    `deprovision_inactive_users` (раздел 16.2). Email последнего активного
    администратора (из тех, кто сохраняет доступ) удалить нельзя: снять
    блокировку было бы некому.
    """
    if not await _is_active_admin_email(db_session, allowed_email.email):
        return
    remaining = await _count_admins_keeping_access(db_session, excluding_email=allowed_email.email)
    if remaining == 0:
        raise ConflictError(
            "Это email последнего активного администратора — "
            "без него система останется без администратора",
        )


async def _users_without_allowed_email(db_session: AsyncSession) -> list[User]:
    stmt = (
        sa.select(User)
        .where(
            User.is_active == True,  # noqa: E712
            ~sa.exists().where(AllowedEmail.email == User.email),
        )
        .order_by(User.created_at)
    )
    return list((await db_session.execute(stmt)).scalars().all())


def _deprovision_log(user: User) -> AppLog:
    return AppLog(
        level=AppLogLevel.WARNING,
        source=DEPROVISION_LOG_SOURCE,
        message=(
            f"Пользователь {user.email} заблокирован: email удалён из allowed_emails. "
            "Вход в трекер и доступ по SFTP закрыты"
        ),
        context={"user_id": str(user.id), "email": user.email, "os_username": user.os_username},
    )


def _kept_admin_log(user: User) -> AppLog:
    return AppLog(
        level=AppLogLevel.ERROR,
        source=DEPROVISION_LOG_SOURCE,
        message=(
            f"Email администратора {user.email} отсутствует в allowed_emails, но он не "
            "заблокирован: иначе в системе не останется ни одного активного администратора. "
            "Верните email в список"
        ),
        context={"user_id": str(user.id), "email": user.email},
    )


async def deprovision_inactive_users(db_session: AsyncSession) -> list[uuid.UUID]:
    """
    Раздел 16.2: блокирует (`is_active = false`) пользователей, чей email
    удалён из `allowed_emails`; вход, API и SFTP-шлюз (он проверяет
    `is_active` на каждой операции) для них закрыты, запись с `os_username`
    пишется в `app_logs`. Повторный запуск идемпотентен: уже заблокированные
    пользователи не выбираются.

    Удалить email последнего администратора нельзя
    (`ensure_allowed_email_deletable`), но email мог пропасть из списка ещё до
    этой проверки. Тогда администраторы не блокируются, если иначе не
    осталось бы ни одного активного, — вместо этого пишется ошибка.
    """
    candidates = await _users_without_allowed_email(db_session)
    candidate_admin_ids = {user.id for user in candidates if user.role is UserRole.ADMIN}
    keep_admins = bool(candidate_admin_ids) and (
        await count_active_admins(db_session) == len(candidate_admin_ids)
    )

    deprovisioned: list[uuid.UUID] = []
    for user in candidates:
        if keep_admins and user.id in candidate_admin_ids:
            db_session.add(_kept_admin_log(user))
            logger.error("deprovision_last_admin_kept", user_id=str(user.id))
            continue
        user.is_active = False
        db_session.add(_deprovision_log(user))
        deprovisioned.append(user.id)
        logger.info("user_deprovisioned", user_id=str(user.id), os_username=user.os_username)
    await db_session.commit()
    return deprovisioned
