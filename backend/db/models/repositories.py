"""Таблицы `repositories`, `templates` (раздел 3.1 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import JsonValue, UUIDPrimaryKeyMixin

# Раздел 3.1: базовая ветка задач репозитория, пока её не задали иначе.
DEFAULT_REPOSITORY_BRANCH = "master"


class GitCredential(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "git_credentials"

    name: Mapped[str] = mapped_column(sa.String)
    kind: Mapped[str] = mapped_column(sa.String)
    host: Mapped[str] = mapped_column(sa.String)
    username: Mapped[str] = mapped_column(sa.String, default="oauth2")
    secret_encrypted: Mapped[str] = mapped_column(sa.Text)
    # Опрос статуса MR через GitLab API (раздел 16.2): без своего токена у
    # `https_token` используется сам токен Git.
    gitlab_api_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    gitlab_api_token_encrypted: Mapped[str | None] = mapped_column(sa.Text)
    gitlab_api_url: Mapped[str | None] = mapped_column(sa.String)


class Repository(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "repositories"

    name: Mapped[str] = mapped_column(sa.String)
    git_url: Mapped[str] = mapped_column(sa.String)
    # Базовая ветка, которую форма задачи подставляет при выборе репозитория.
    default_branch: Mapped[str] = mapped_column(
        sa.String,
        default=DEFAULT_REPOSITORY_BRANCH,
        server_default=DEFAULT_REPOSITORY_BRANCH,
    )
    default_template_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("templates.id"))
    git_credential_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("git_credentials.id"))
    git_credential: Mapped[GitCredential | None] = relationship(lazy="selectin")


class Template(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "templates"

    name: Mapped[str] = mapped_column(sa.String)
    # Дерево файлов шаблона (CLAUDE.md, .claude/commands/*.md, .claude/settings.json).
    files: Mapped[JsonValue] = mapped_column(JSONB)
    # Пути из `files`, загруженные с диска: форма открывает их в режиме «Из файла».
    uploaded_file_paths: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    # Раздел 19.2: шаблон — личный; шаблон репозитория по умолчанию при этом
    # применяется к задачам любого пользователя (решение №16 плана).
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)


class TemplateMcpServer(Base):
    """
    Связь многие-ко-многим для `templates.mcp_server_ids` (раздел 3.1): в
    отличие от массива UUID, у каждой ссылки есть настоящий внешний ключ.
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
