"""
Таблицы `task_categories`, `task_category_library_prompts` (раздел 3.1, 15.7 ТЗ).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.mixins import CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin
from db.models.tasks import DEFAULT_QUEUE_PRIORITY, MAX_QUEUE_PRIORITY, MIN_QUEUE_PRIORITY


class TaskCategory(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    """
    Категория задачи — личная (раздел 19.2): её настройки копируются в новую
    задачу категории (раздел 15.7).
    """

    __tablename__ = "task_categories"
    __table_args__ = (
        sa.UniqueConstraint("created_by", "name", name="uq_task_categories_owner_name"),
        sa.CheckConstraint(
            f"queue_priority BETWEEN {MIN_QUEUE_PRIORITY} AND {MAX_QUEUE_PRIORITY}",
            name="ck_task_categories_queue_priority",
        ),
    )

    name: Mapped[str] = mapped_column(sa.String)
    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("pipelines.id", ondelete="SET NULL"),
    )
    auto_accept_plan: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    queue_priority: Mapped[int] = mapped_column(
        sa.Integer,
        default=DEFAULT_QUEUE_PRIORITY,
        server_default=str(DEFAULT_QUEUE_PRIORITY),
    )
    occupies_slot: Mapped[bool] = mapped_column(
        sa.Boolean,
        default=False,
        server_default=sa.false(),
    )
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)


class TaskCategoryLibraryPrompt(Base):
    """
    Системные промты категории — копируются в список промтов новой задачи.
    """

    __tablename__ = "task_category_library_prompts"

    category_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("task_categories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
