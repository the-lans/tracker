"""Web Push — регистрация подписки и раздача публичного VAPID-ключа
(раздел 18.1 ТЗ: "подписка запрашивается при первом входе")."""

from __future__ import annotations

import os
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import PushSubscriptionRequest, VapidPublicKeyResponse
from db.models.notifications import PushSubscription
from db.models.users import User
from db.session import get_session

router = APIRouter(prefix="/push", tags=["push"])

_VAPID_PUBLIC_KEY_ENV = "VAPID_PUBLIC_KEY"


@router.get("/vapid-public-key", response_model=VapidPublicKeyResponse)
async def get_vapid_public_key() -> VapidPublicKeyResponse:
    return VapidPublicKeyResponse(public_key=os.environ[_VAPID_PUBLIC_KEY_ENV])


@router.post("/subscriptions", status_code=204)
async def create_push_subscription(
    body: PushSubscriptionRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Идемпотентно: повторная подписка с тем же ``endpoint`` (например,
    после обновления ключей браузером) обновляет существующую запись, а не
    плодит дубликаты — `endpoint` уникален на уровне БД."""
    existing = await db_session.scalar(
        sa.select(PushSubscription).where(PushSubscription.endpoint == body.endpoint),
    )
    if existing is not None:
        existing.user_id = current_user.id
        existing.p256dh_key = body.keys.p256dh
        existing.auth_key = body.keys.auth
    else:
        db_session.add(
            PushSubscription(
                user_id=current_user.id,
                endpoint=body.endpoint,
                p256dh_key=body.keys.p256dh,
                auth_key=body.keys.auth,
            ),
        )
    await db_session.commit()


@router.delete("/subscriptions", status_code=204)
async def delete_push_subscription(
    endpoint: str,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    await db_session.execute(
        sa.delete(PushSubscription).where(PushSubscription.endpoint == endpoint),
    )
    await db_session.commit()
