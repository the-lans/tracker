"""Метаданные разделов и файлов общей базы знаний."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.mixins import CreatedAtMixin, CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin


class KnowledgeSection(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "knowledge_sections"
    __table_args__ = (
        sa.UniqueConstraint("name", name="uq_knowledge_sections_name"),
        sa.CheckConstraint("NOT user_write OR user_read", name="ck_knowledge_section_write_read"),
    )

    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    user_read: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false())
    user_write: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false())
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))


class KnowledgeEntry(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "knowledge_entries"
    __table_args__ = (
        sa.UniqueConstraint("section_id", "path", name="uq_knowledge_entry_path"),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_entry_version"),
    )

    section_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("knowledge_sections.id"), index=True
    )
    path: Mapped[str] = mapped_column(sa.String(1024))
    is_directory: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false())
    version: Mapped[int] = mapped_column(sa.Integer, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class KnowledgeVersion(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (sa.UniqueConstraint("entry_id", "version", name="uq_knowledge_version"),)

    entry_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("knowledge_entries.id"), index=True)
    version: Mapped[int] = mapped_column(sa.Integer)
    operation: Mapped[str] = mapped_column(sa.String(32), server_default="save")
    path: Mapped[str | None] = mapped_column(sa.String(1024))
    storage_key: Mapped[str] = mapped_column(sa.String(255))
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
