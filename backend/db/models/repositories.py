"""Таблицы `repositories`, `templates` (раздел 3.1 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.mixins import JsonValue, UUIDPrimaryKeyMixin


class Repository(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "repositories"

    name: Mapped[str] = mapped_column(sa.String)
    git_url: Mapped[str] = mapped_column(sa.String)
    default_template_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("templates.id"))
    deploy_key_encrypted: Mapped[str] = mapped_column(sa.Text)


class Template(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "templates"

    name: Mapped[str] = mapped_column(sa.String)
    # Дерево файлов шаблона (CLAUDE.md, .claude/commands/*.md, .claude/settings.json).
    files: Mapped[JsonValue] = mapped_column(JSONB)


class TemplateMcpServer(Base):
    """Связь многие-ко-многим для `templates.mcp_server_ids` (3.1).

    ТЗ описывает поле как "array of FK → mcp_servers" внутри таблицы
    `templates`; реализовано как отдельная association-таблица — тот же
    факт связи, но с honest FK-целостностью, которую сырой массив UUID не
    даёт бесплатно.
    """

    __tablename__ = "template_mcp_servers"

    template_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("templates.id"),
        primary_key=True,
    )
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("mcp_servers.id"),
        primary_key=True,
    )
