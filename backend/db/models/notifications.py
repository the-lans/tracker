"""Таблица `push_subscriptions` (раздел 18.1 ТЗ).

Не входит в перечень 17 таблиц раздела 3.1 — прямое следствие Web Push
(Service Worker + Push API, "подписка запрашивается при первом входе"):
подписке нужно где-то храниться, а ТЗ не называет для неё поле в уже
описанных таблицах.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class PushSubscription(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Один браузер/устройство одного пользователя — одна подписка Push API.

    Поля дублируют `PushSubscriptionJSON` из стандарта Push API
    (endpoint + keys.p256dh + keys.auth) — именно этот набор нужен
    `pywebpush`, ничего сверх этого.
    """

    __tablename__ = "push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    endpoint: Mapped[str] = mapped_column(sa.Text, unique=True)
    p256dh_key: Mapped[str] = mapped_column(sa.Text)
    auth_key: Mapped[str] = mapped_column(sa.Text)
