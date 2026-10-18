"""`api/push.py` — раздел 18.1 ТЗ."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.notifications import PushSubscription

if TYPE_CHECKING:
    from httpx import AsyncClient


async def test_get_vapid_public_key(authed_client: AsyncClient) -> None:
    response = await authed_client.get("/push/vapid-public-key")

    assert response.status_code == 200
    assert response.json()["public_key"] == "test-vapid-public-key"


async def test_create_subscription(authed_client: AsyncClient, db_session: AsyncSession) -> None:
    endpoint = f"https://push.example.com/{uuid.uuid4()}"

    response = await authed_client.post(
        "/push/subscriptions",
        json={"endpoint": endpoint, "keys": {"p256dh": "p256dh-value", "auth": "auth-value"}},
    )

    assert response.status_code == 204
    stored = await db_session.scalar(
        sa.select(PushSubscription).where(PushSubscription.endpoint == endpoint),
    )
    assert stored is not None
    assert stored.p256dh_key == "p256dh-value"


async def test_resubscribing_same_endpoint_updates_instead_of_duplicating(
    authed_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    endpoint = f"https://push.example.com/{uuid.uuid4()}"
    body: dict[str, Any] = {"endpoint": endpoint, "keys": {"p256dh": "first", "auth": "auth-value"}}
    await authed_client.post("/push/subscriptions", json=body)

    body["keys"]["p256dh"] = "second"
    response = await authed_client.post("/push/subscriptions", json=body)

    assert response.status_code == 204
    rows = list(
        (
            await db_session.execute(
                sa.select(PushSubscription).where(PushSubscription.endpoint == endpoint),
            )
        )
        .scalars()
        .all(),
    )
    assert len(rows) == 1
    assert rows[0].p256dh_key == "second"


async def test_delete_subscription(authed_client: AsyncClient, db_session: AsyncSession) -> None:
    endpoint = f"https://push.example.com/{uuid.uuid4()}"
    await authed_client.post(
        "/push/subscriptions",
        json={"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}},
    )

    response = await authed_client.delete("/push/subscriptions", params={"endpoint": endpoint})

    assert response.status_code == 204
    stored = await db_session.scalar(
        sa.select(PushSubscription).where(PushSubscription.endpoint == endpoint),
    )
    assert stored is None
