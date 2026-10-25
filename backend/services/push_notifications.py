"""Web Push (раздел 18.1 ТЗ) — уведомление, доставляемое даже при закрытой
вкладке браузера, в дополнение к WebSocket-каналу `api/ws.py`.

`WebPushSender` — тот же приём DI, что и `GoogleIdTokenVerifier`/
`ClaudeAgentClientProtocol`: реальная отправка (`PywebpushSender`) требует
сети и настоящих VAPID-ключей, тесты подставляют фейк.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import sqlalchemy as sa
from pywebpush import WebPushException, webpush

from app_logging.config import get_logger
from db.models.notifications import PushSubscription

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("push_notifications")

_VAPID_PRIVATE_KEY_ENV = "VAPID_PRIVATE_KEY"
_VAPID_PUBLIC_KEY_ENV = "VAPID_PUBLIC_KEY"
_VAPID_CLAIMS_EMAIL_ENV = "VAPID_CLAIMS_EMAIL"

# Раздел 18.1: подписка живёт, пока браузер её не отзовёт — истёкшую
# подписку сервер узнаёт только по ответу push-службы (410 Gone/404 Not
# Found), поэтому чистка ленивая (при следующей неудачной отправке), а не
# по TTL.
_EXPIRED_SUBSCRIPTION_STATUS_CODES = frozenset({404, 410})
# Push-служба, принявшая соединение и не отвечающая, не должна держать
# отправителя: у `webpush` по умолчанию ожидание не ограничено.
PUSH_SEND_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class PushMessage:
    title: str
    body: str
    data: dict[str, str]


class SubscriptionExpiredError(Exception):
    """Push-служба сообщила, что подписка больше не действительна (404/410)."""


class WebPushSender(Protocol):
    def send(self, *, subscription: PushSubscription, message: PushMessage) -> None: ...


class PywebpushSender:
    """Реальная отправка через `pywebpush` — требует настоящих VAPID-ключей
    в окружении и сетевого доступа к push-службе браузера."""

    def send(self, *, subscription: PushSubscription, message: PushMessage) -> None:
        subscription_info = {
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh_key, "auth": subscription.auth_key},
        }
        payload = json.dumps({"title": message.title, "body": message.body, "data": message.data})
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=os.environ[_VAPID_PRIVATE_KEY_ENV],
                vapid_claims={"sub": f"mailto:{os.environ[_VAPID_CLAIMS_EMAIL_ENV]}"},
                timeout=PUSH_SEND_TIMEOUT_SECONDS,
            )
        except WebPushException as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in _EXPIRED_SUBSCRIPTION_STATUS_CODES:
                raise SubscriptionExpiredError(str(exc)) from exc
            raise


async def send_push_to_user(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    message: PushMessage,
    sender: WebPushSender | None = None,
) -> None:
    """Отправляет `message` во все подписки пользователя; истёкшие подписки
    (404/410 от push-службы) удаляются немедленно, не дожидаясь отдельной
    периодической задачи очистки — раздел 18.1 не предполагает отдельного
    TTL-механизма для них.

    Отправка синхронная (HTTP через `requests`) и идёт в отдельном потоке:
    иначе медленная push-служба остановила бы event loop вызывающего — в
    воркере сессии вместе с пульсом сессии (раздел 6.6)."""
    active_sender = sender or PywebpushSender()
    stmt = sa.select(PushSubscription).where(PushSubscription.user_id == user_id)
    subscriptions = list((await db_session.execute(stmt)).scalars().all())
    for subscription in subscriptions:
        try:
            await asyncio.to_thread(active_sender.send, subscription=subscription, message=message)
        except SubscriptionExpiredError:
            logger.info("push_subscription_expired", subscription_id=str(subscription.id))
            await db_session.delete(subscription)
        except Exception as exc:  # noqa: BLE001 — раздел 18: сбой одной подписки не должен прервать остальные
            logger.error(
                "push_send_failed",
                subscription_id=str(subscription.id),
                error=str(exc),
            )
    await db_session.commit()
