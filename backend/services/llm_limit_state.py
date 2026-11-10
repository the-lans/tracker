"""
Состояние лимита LLM-аккаунтов для списка «LLM-аккаунты» (разделы 15.1, 19.7 ТЗ).

Тот же расчёт, что у выбора аккаунта хода (`services/llm_account_choice.limit_state`):
«Запущен», «Свободен», «На пороге», «Исчерпан» с временем сброса и числом
задач в работе на аккаунте. Порог — из профиля владельца аккаунта, нагрузка
собирается одним проходом по аккаунтам списка.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlalchemy as sa

from db.models.enums import NodeLogStatus
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import User
from services.account_router import IN_WORK_STATUSES
from services.llm_account_choice import AccountView, LimitState, limit_state

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.llm import LlmAccount


@dataclass(frozen=True, slots=True)
class AccountLimitInfo:
    state: LimitState
    # Сброс окна или недели, когда состояние кончится; None — не ограничено.
    until: datetime | None
    active_tasks: int


async def _counts(
    db_session: AsyncSession,
    stmt: sa.Select[uuid.UUID | None, int],
) -> dict[uuid.UUID | None, int]:
    return {key: count for key, count in await db_session.execute(stmt)}


async def account_limit_states(
    db_session: AsyncSession,
    accounts: Sequence[LlmAccount],
    *,
    now: datetime,
) -> dict[uuid.UUID, AccountLimitInfo]:
    """Состояние каждого аккаунта списка по порогу его владельца."""
    if not accounts:
        return {}
    account_ids = [account.id for account in accounts]
    owner_ids = {account.created_by for account in accounts}
    tasks = await _counts(
        db_session,
        sa.select(Task.current_llm_account_id, sa.func.count(Task.id))
        .where(
            Task.status.in_(IN_WORK_STATUSES),
            Task.current_llm_account_id.in_(account_ids),
        )
        .group_by(Task.current_llm_account_id),
    )
    turns = await _counts(
        db_session,
        sa.select(NodeLog.llm_account_id, sa.func.count(NodeLog.id))
        .where(
            NodeLog.status == NodeLogStatus.RUNNING,
            NodeLog.llm_account_id.in_(account_ids),
        )
        .group_by(NodeLog.llm_account_id),
    )
    thresholds = {
        user_id: threshold
        for user_id, threshold in await db_session.execute(
            sa.select(User.id, User.llm_switch_threshold_5h_pct).where(User.id.in_(owner_ids)),
        )
    }
    states: dict[uuid.UUID, AccountLimitInfo] = {}
    for account in accounts:
        view = AccountView(
            account,
            tasks=tasks.get(account.id, 0),
            running_turns=turns.get(account.id, 0),
        )
        limit = limit_state(view, threshold_pct=thresholds[account.created_by], now=now)
        states[account.id] = AccountLimitInfo(
            state=limit.state,
            until=limit.until,
            active_tasks=view.tasks,
        )
    return states
