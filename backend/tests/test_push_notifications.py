"""`services/push_notifications.py` — раздел 18.1 ТЗ."""

from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.notifications import PushSubscription
from db.models.users import User
from services.push_notifications import (
    PushMessage,
    PywebpushSender,
    SubscriptionExpiredError,
    WebPushSender,
    send_push_to_user,
)


class _RecordingSender:
    def __init__(self) -> None:
        self.sent: list[PushSubscription] = []

    def send(self, *, subscription: PushSubscription, message: PushMessage) -> None:
        self.sent.append(subscription)


class _AlwaysExpiredSender:
    def send(self, *, subscription: PushSubscription, message: PushMessage) -> None:
        raise SubscriptionExpiredError("gone")


class _AlwaysFailingSender:
    def send(self, *, subscription: PushSubscription, message: PushMessage) -> None:
        raise RuntimeError("network error")


async def _make_user(db_session: AsyncSession) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@example.com", is_active=True)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_subscription(db_session: AsyncSession, user: User) -> PushSubscription:
    subscription = PushSubscription(
        user_id=user.id,
        endpoint=f"https://push.example.com/{uuid.uuid4()}",
        p256dh_key="p256dh",
        auth_key="auth",
    )
    db_session.add(subscription)
    await db_session.flush()
    return subscription


async def test_sends_to_every_subscription_of_the_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    await _make_subscription(db_session, user)
    await _make_subscription(db_session, user)
    sender: WebPushSender = _RecordingSender()

    await send_push_to_user(
        db_session,
        user_id=user.id,
        message=PushMessage(title="t", body="b", data={}),
        sender=sender,
    )

    assert len(sender.sent) == 2  # type: ignore[attr-defined]


async def test_expired_subscription_is_deleted(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    subscription = await _make_subscription(db_session, user)

    await send_push_to_user(
        db_session,
        user_id=user.id,
        message=PushMessage(title="t", body="b", data={}),
        sender=_AlwaysExpiredSender(),
    )

    assert await db_session.get(PushSubscription, subscription.id) is None


async def test_generic_send_failure_does_not_raise_or_delete_subscription(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    subscription = await _make_subscription(db_session, user)

    await send_push_to_user(
        db_session,
        user_id=user.id,
        message=PushMessage(title="t", body="b", data={}),
        sender=_AlwaysFailingSender(),
    )

    assert await db_session.get(PushSubscription, subscription.id) is not None


async def test_no_subscriptions_is_a_no_op(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)

    await send_push_to_user(
        db_session,
        user_id=user.id,
        message=PushMessage(title="t", body="b", data={}),
        sender=_RecordingSender(),
    )


def test_pywebpush_sender_translates_410_to_expired_error() -> None:
    from pywebpush import WebPushException

    subscription = PushSubscription(
        user_id=uuid.uuid4(),
        endpoint="https://push.example.com/x",
        p256dh_key="p256dh",
        auth_key="auth",
    )
    exc = WebPushException("gone", response=Mock(status_code=410))
    with patch("services.push_notifications.webpush", side_effect=exc):
        with pytest.raises(SubscriptionExpiredError):
            PywebpushSender().send(
                subscription=subscription,
                message=PushMessage(title="t", body="b", data={}),
            )


def test_pywebpush_sender_reraises_non_expiry_errors() -> None:
    from pywebpush import WebPushException

    subscription = PushSubscription(
        user_id=uuid.uuid4(),
        endpoint="https://push.example.com/x",
        p256dh_key="p256dh",
        auth_key="auth",
    )
    exc = WebPushException("server error", response=Mock(status_code=500))
    with patch("services.push_notifications.webpush", side_effect=exc):
        with pytest.raises(WebPushException):
            PywebpushSender().send(
                subscription=subscription,
                message=PushMessage(title="t", body="b", data={}),
            )
