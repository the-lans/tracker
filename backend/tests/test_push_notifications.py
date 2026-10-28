"""`services/push_notifications.py` — раздел 18.1 ТЗ."""

from __future__ import annotations

import asyncio
import threading
import uuid
from unittest.mock import Mock, patch

import pytest
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.notifications import PushSubscription
from db.models.tasks import Task
from db.models.users import User
from services import notifications
from services.notifications import NotificationEvent, notify_task_event
from services.push_notifications import (
    PUSH_SEND_TIMEOUT_SECONDS,
    PushMessage,
    PywebpushSender,
    SubscriptionExpiredError,
    WebPushSender,
    send_push_to_user,
)
from tests.factories import make_user


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
    user = await make_user(db_session)
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
    user = await make_user(db_session)
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
    user = await make_user(db_session)
    subscription = await _make_subscription(db_session, user)

    await send_push_to_user(
        db_session,
        user_id=user.id,
        message=PushMessage(title="t", body="b", data={}),
        sender=_AlwaysFailingSender(),
    )

    assert await db_session.get(PushSubscription, subscription.id) is not None


class TestSendLogs:
    """Раздел 18.1: по логам видно, ушло ли уведомление в каждую подписку."""

    @pytest.mark.parametrize(
        ("sender", "event"),
        [
            (_RecordingSender(), "push_sent"),
            (_AlwaysFailingSender(), "push_send_failed"),
            (_AlwaysExpiredSender(), "push_subscription_expired"),
        ],
        ids=["sent", "failed", "expired"],
    )
    async def test_outcome_logged(
        self,
        db_session: AsyncSession,
        sender: WebPushSender,
        event: str,
    ) -> None:
        user = await make_user(db_session)
        subscription = await _make_subscription(db_session, user)

        with structlog.testing.capture_logs() as logs:
            await send_push_to_user(
                db_session,
                user_id=user.id,
                message=PushMessage(title="t", body="b", data={}),
                sender=sender,
            )

        assert [(entry["event"], entry["subscription_id"]) for entry in logs] == [
            (event, str(subscription.id)),
        ]


async def test_no_subscriptions_is_a_no_op(db_session: AsyncSession) -> None:
    user = await make_user(db_session)

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


class _BlockingSender:
    """Медленная push-служба: отправка держит поток, пока не отпустят."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def send(self, *, subscription: PushSubscription, message: PushMessage) -> None:
        self.release.wait(timeout=5)


class TestSendDoesNotBlockLoop:
    """Раздел 6.6: отправка не останавливает event loop вызывающего (пульс сессии)."""

    async def test_loop_keeps_running(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        await _make_subscription(db_session, user)
        sender = _BlockingSender()
        sending = asyncio.create_task(
            send_push_to_user(
                db_session,
                user_id=user.id,
                message=PushMessage(title="t", body="b", data={}),
                sender=sender,
            ),
        )

        await asyncio.sleep(0.05)
        assert not sending.done()
        sender.release.set()
        await sending

    def test_pywebpush_timeout_is_bounded(self) -> None:
        subscription = PushSubscription(
            user_id=uuid.uuid4(),
            endpoint="https://push.example.com/x",
            p256dh_key="p256dh",
            auth_key="auth",
        )
        with patch("services.push_notifications.webpush") as webpush:
            PywebpushSender().send(
                subscription=subscription,
                message=PushMessage(title="t", body="b", data={}),
            )

        assert webpush.call_args.kwargs["timeout"] == PUSH_SEND_TIMEOUT_SECONDS


class TestNotifyTaskEvent:
    async def test_push_logged_with_task_id(
        self,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Раздел 17.2: итог отправки ищется по задаче и вне воркера сессии."""
        seen: list[object] = []

        async def record(*_args: object, **_kwargs: object) -> None:
            seen.append(structlog.contextvars.get_contextvars().get("task_id"))

        monkeypatch.setattr(notifications, "send_push_to_user", record)
        user = await make_user(db_session)
        task = Task(code="RR-12345", title="t", description="d", created_by=user.id)

        await notify_task_event(db_session, event=NotificationEvent.DONE, task=task)

        assert seen == [str(task.id)]
        assert "task_id" not in structlog.contextvars.get_contextvars()
