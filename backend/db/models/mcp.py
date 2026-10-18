"""Таблица `mcp_servers` (раздел 3.1, 10.2 ТЗ)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import McpAuthType, McpIsolationMode
from db.models.mixins import UUIDPrimaryKeyMixin, pg_enum


class McpServer(UUIDPrimaryKeyMixin, Base):
    """MCP-сервер, включая поля изоляции ресурсов с состоянием (раздел 10).

    Правило "``has_stateful_resource = true`` требует ``isolation_mode`` не
    ``NULL``/``none``" (3.2) намеренно НЕ выражено здесь CHECK-constraint'ом —
    ТЗ явно относит эту проверку к валидации API, а не к БД (см.
    `docs/implementation_plan.md`, этап 2); реализуется в `services/`.
    """

    __tablename__ = "mcp_servers"

    name: Mapped[str] = mapped_column(sa.String)
    url: Mapped[str] = mapped_column(sa.String)
    auth_type: Mapped[McpAuthType] = mapped_column(pg_enum(McpAuthType, name="mcp_auth_type"))
    auth_config_encrypted: Mapped[str] = mapped_column(sa.Text)
    is_healthy: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    has_stateful_resource: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    isolation_mode: Mapped[McpIsolationMode | None] = mapped_column(
        pg_enum(McpIsolationMode, name="mcp_isolation_mode"),
    )
    isolation_path_template: Mapped[str | None] = mapped_column(sa.String)
