"""Таблица `llm_accounts` (раздел 3.1 ТЗ)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.enums import LlmAccountStatus, ReasoningEffort
from db.models.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin, pg_enum

DEFAULT_PROVIDER = "anthropic"
# Расход окна лимита в процентах с двумя знаками (раздел 3.1).
USAGE_PCT_TYPE = sa.Numeric(5, 2)


class LlmAccount(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Вход пользователя в подписку провайдера, сохранённый в LLM-прокси (раздел 19.5)."""

    __tablename__ = "llm_accounts"
    __table_args__ = (
        # Отложенная проверка: перестановка ↑/↓ меняет два места в одной транзакции.
        sa.UniqueConstraint(
            "created_by",
            "switch_order",
            name="uq_llm_accounts_owner_switch_order",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    label: Mapped[str] = mapped_column(sa.String)
    # Идентификатор провайдера из реестра `services/llm_providers.py` (раздел 19.7).
    provider: Mapped[str] = mapped_column(
        sa.String,
        default=DEFAULT_PROVIDER,
        server_default=DEFAULT_PROVIDER,
    )
    # Имя учётки в прокси; пусто, пока вход не выполнен.
    cliproxy_credential: Mapped[str | None] = mapped_column(sa.String, unique=True)
    # `acc-<12 hex id>`: запрос `<префикс>/<модель>` прокси выполняет только этой учёткой.
    cliproxy_prefix: Mapped[str] = mapped_column(sa.String, unique=True)
    default_model: Mapped[str | None] = mapped_column(sa.String)
    default_effort: Mapped[ReasoningEffort] = mapped_column(
        pg_enum(ReasoningEffort, name="reasoning_effort"),
        default=ReasoningEffort.HIGH,
        server_default=ReasoningEffort.HIGH.value,
    )
    switch_order: Mapped[int] = mapped_column(sa.Integer)
    # Устарело: каталог входа в Claude до прокси — нужен только переносу
    # истории сессий при обновлении (раздел 20.6), новые аккаунты его не заполняют.
    claude_config_dir: Mapped[str | None] = mapped_column(sa.String, unique=True)
    status: Mapped[LlmAccountStatus] = mapped_column(
        pg_enum(LlmAccountStatus, name="llm_account_status"),
        default=LlmAccountStatus.LOGIN_REQUIRED,
    )
    # Когда истекает исчерпанное окно лимита (раздел 16.2, `check_llm_account_limits`).
    rate_limit_resets_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Расход окон по последнему опросу через прокси (раздел 19.7); NULL — неизвестен.
    usage_5h_pct: Mapped[Decimal | None] = mapped_column(USAGE_PCT_TYPE)
    usage_week_pct: Mapped[Decimal | None] = mapped_column(USAGE_PCT_TYPE)
    usage_5h_resets_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    usage_week_resets_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    usage_checked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Раздел 19.7: окно открыл трекер первым ходом — опрос видит его с задержкой.
    window_started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    # Средняя стоимость хода в процентах 5-часового окна — резерв идущих ходов.
    turn_cost_pct: Mapped[Decimal | None] = mapped_column(USAGE_PCT_TYPE)
    # Раздел 19.2: аккаунт личный — владелец тот, кто его завёл.
    created_by: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)

    @property
    def signed_in(self) -> bool:
        """Вход выполнен: у аккаунта есть учётка в прокси."""
        return self.cliproxy_credential is not None
