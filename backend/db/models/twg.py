"""Личное подключение пользователя к Teamwork Graph CLI."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class TwgConnection(Base):
    __tablename__ = "twg_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), primary_key=True)
    site: Mapped[str] = mapped_column(sa.String)
    email: Mapped[str] = mapped_column(sa.String)
    token_encrypted: Mapped[str] = mapped_column(sa.Text)
