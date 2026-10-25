"""Таблицы `pipelines`, `nodes`, `task_nodes` (раздел 3.1 ТЗ)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import NodeType, ScriptLanguage
from db.models.mixins import CreatedAtMixin, CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin, pg_enum

_DEFAULT_TIMEOUT_SECONDS = 600
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY_SECONDS = 5


class Pipeline(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "pipelines"

    name: Mapped[str] = mapped_column(sa.String)
    # Раздел 3.1, 3.2: используемый задачей пайплайн вместо удаления архивируется.
    is_archived: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    # Раздел 19.2: пайплайн — личный, `user` видит и меняет только свои.
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)


class Node(UUIDPrimaryKeyMixin, Base):
    """Нода пайплайна, системный промт библиотеки и своя нода задачи — одна сущность (3.1).

    У ноды заполнено ровно одно из ``pipeline_id`` и ``task_id``, у промта
    библиотеки — ни одно; ``is_library_item`` дублирует этот факт явным
    полем (ТЗ: "хранится отдельно для явности и быстрой фильтрации") —
    согласованность защищена ``CheckConstraint`` ниже.
    """

    __tablename__ = "nodes"
    __table_args__ = (
        sa.CheckConstraint(
            "(is_library_item AND pipeline_id IS NULL AND task_id IS NULL) "
            "OR (NOT is_library_item AND num_nonnulls(pipeline_id, task_id) = 1)",
            name="ck_nodes_is_library_item_matches_pipeline_id",
        ),
    )

    pipeline_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("pipelines.id"))
    # Раздел 13.1: своя нода, вставленная в снимок `task_nodes` только этой задачи.
    task_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("tasks.id"), index=True)
    order_index: Mapped[int | None] = mapped_column(sa.Integer)
    name: Mapped[str] = mapped_column(sa.String)
    description: Mapped[str | None] = mapped_column(sa.Text)
    node_type: Mapped[NodeType] = mapped_column(pg_enum(NodeType, name="node_type"))
    prompt_template: Mapped[str | None] = mapped_column(sa.Text)
    # Литеральная строка вызова слэш-команды — никогда не проходит через
    # шаблонизатор проекта (раздел 4 ТЗ).
    command_invocation: Mapped[str | None] = mapped_column(sa.String)
    script_language: Mapped[ScriptLanguage | None] = mapped_column(
        pg_enum(ScriptLanguage, name="script_language"),
    )
    script_content: Mapped[str | None] = mapped_column(sa.Text)
    docker_image: Mapped[str | None] = mapped_column(sa.String)
    timeout_seconds: Mapped[int] = mapped_column(sa.Integer, default=_DEFAULT_TIMEOUT_SECONDS)
    max_retries: Mapped[int] = mapped_column(sa.Integer, default=_DEFAULT_MAX_RETRIES)
    retry_base_delay_seconds: Mapped[int] = mapped_column(
        sa.Integer,
        default=_DEFAULT_RETRY_BASE_DELAY_SECONDS,
    )
    guide_url: Mapped[str | None] = mapped_column(sa.String)
    is_skipped: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    is_library_item: Mapped[bool] = mapped_column(sa.Boolean)
    # Раздел 3.1, 5: параметр N переменной `{{node.llm_output_last_n}}`. NULL —
    # переменная не настроена для ноды (использование в шаблоне этой ноды не
    # проходит валидацию сохранения).
    llm_output_last_n: Mapped[int | None] = mapped_column(sa.Integer)
    # Раздел 3.1, 3.2: архивация системного промта библиотеки.
    is_archived: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    # Раздел 19.2: у ноды пайплайна — автор пайплайна, у промта библиотеки —
    # тот, кто его создал; доступ к любой ноде проверяется по этому полю.
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)


class TaskNode(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Снимок ноды пайплайна для конкретной задачи (3.1): нода — не больше одного раза."""

    __tablename__ = "task_nodes"
    __table_args__ = (
        sa.Index("uq_task_nodes_task_id_node_id", "task_id", "node_id", unique=True),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("tasks.id"))
    node_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("nodes.id"))
    order_index: Mapped[int] = mapped_column(sa.Integer)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Раздел 13.1: после успеха ноды задача встаёт в `paused`.
    pause_after: Mapped[bool] = mapped_column(sa.Boolean, default=False)
