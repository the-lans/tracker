"""
Аккаунт хода сессии задачи (раздел 19.7 ТЗ).

Перед каждым обращением к сессии воркер спрашивает `TaskAccountRouter.route`:
роутер обновляет расход прежнего аккаунта задачи, если опрос устарел,
выбирает аккаунт по порогам автора (`services/llm_routing.choose_account`),
публикует маршрут для `llm-gateway` и выставляет `tasks.current_llm_account_id`.
Смена аккаунта пишется событием `llm_account_switched`; если все аккаунты
выше порога — автору уходит уведомление не чаще раза в час.

Ошибка хода, в которой провайдер отклонил вход или исчерпан лимит, переводит
аккаунт маршрута в `login_required`/`rate_limited` (`report_error`); повтор
ноды выберет аккаунт заново.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa
from redis.exceptions import RedisError

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from db.models.enums import (
    AppLogLevel,
    LlmAccountStatus,
    LlmSwitchReason,
    NodeType,
    ReasoningEffort,
)
from db.models.llm import LlmAccount
from db.models.tasks import Task
from db.models.users import User
from services.errors import ExternalServiceError
from services.llm_account_checks import require_login
from services.llm_providers import PROVIDERS, get_provider, provider_effort
from services.llm_routing import (
    AccountChoice,
    NoLlmAccountAvailableError,
    SwitchThresholds,
    TurnRoute,
    choose_account,
    publish_route,
)
from services.llm_usage import refresh_account_usage
from services.notifications import NotificationEvent, notify_task_event

if TYPE_CHECKING:
    from claude_agent_sdk import RateLimitInfo
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient

logger = get_logger("account_router")

_SOURCE = "account_router"
# Раздел 19.7: перед выбором расход обновляется, если опрос старше минуты.
USAGE_MAX_AGE = timedelta(seconds=60)
# Раздел 18.2: «все выше порога» — не чаще раза в час на пользователя.
ABOVE_THRESHOLD_PUSH_WINDOW_SECONDS = 60 * 60
_ABOVE_THRESHOLD_PUSH_KEY = "push:window:llm_above_threshold:{user_id}"
# Ошибка `rate_limit` без времени сброса: окно лимита неизвестно, аккаунт
# возвращается в работу проверкой `check_llm_account_limits` через час.
_UNKNOWN_RATE_LIMIT_WINDOW = timedelta(hours=1)
_REJECTED = "rejected"

AUTHENTICATION_FAILED = "authentication_failed"
RATE_LIMIT = "rate_limit"

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TaskAccountRouter:
    """Выбор аккаунта на каждый ход сессии одной задачи; живёт, пока воркер держит сессию."""

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        redis_client: Redis,
        task: Task,
        cliproxy: CliproxyManagementClient,
        clock: Clock = _utcnow,
    ) -> None:
        self._db = db_session
        self._redis = redis_client
        self._task = task
        self._cliproxy = cliproxy
        self._clock = clock
        self.route_in_use: TurnRoute | None = None

    async def route(
        self,
        *,
        effort: ReasoningEffort | None,
        node_type: NodeType | None,
    ) -> TurnRoute:
        """
        Маршрут хода: аккаунт, модель и уровень рассуждений. Нет ни одного
        `active` аккаунта — `NoLlmAccountAvailableError` (п. 5 раздела 19.7).
        """
        task = self._task
        await self._db.refresh(task, ["current_llm_account_id", "llm_account_id"])
        accounts = await self._accounts()
        previous_id = task.current_llm_account_id or task.llm_account_id
        await self._refresh_stale_usage(accounts, previous_id)
        choice = choose_account(
            accounts,
            current_id=task.current_llm_account_id,
            start_id=task.llm_account_id,
            thresholds=await self._thresholds(),
            plan_prompt=node_type is NodeType.PLAN_PROMPT,
        )
        switched = previous_id is not None and previous_id != choice.account.id
        route = _turn_route(
            choice.account,
            effort,
            switch_reason=choice.reason if switched else None,
        )
        await publish_route(self._redis, task.id, route)
        await self._set_current(choice)
        if switched:
            assert previous_id is not None
            await self._log_switch(previous_id, choice)
        if choice.reason is LlmSwitchReason.ALL_ABOVE_THRESHOLD:
            await self._notify_all_above_threshold()
        self.route_in_use = route
        return route

    async def _accounts(self) -> list[LlmAccount]:
        stmt = (
            sa.select(LlmAccount)
            .where(LlmAccount.created_by == self._task.created_by)
            .order_by(LlmAccount.switch_order)
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars())

    async def _thresholds(self) -> SwitchThresholds:
        author = await self._db.get(User, self._task.created_by)
        assert author is not None
        return SwitchThresholds(
            five_hour=author.llm_switch_threshold_5h_pct,
            week=author.llm_switch_threshold_week_pct,
        )

    async def _refresh_stale_usage(
        self,
        accounts: list[LlmAccount],
        account_id: uuid.UUID | None,
    ) -> None:
        account = next((item for item in accounts if item.id == account_id), None)
        if account is None or not _usage_stale(account, now=self._clock()):
            return
        auth_index = await self._auth_index(account)
        if auth_index is None:
            return
        await refresh_account_usage(
            self._cliproxy,
            account,
            auth_index=auth_index,
            now=self._clock(),
        )
        await self._db.commit()

    async def _auth_index(self, account: LlmAccount) -> str | None:
        try:
            credentials = await self._cliproxy.list_credentials()
        except ExternalServiceError as exc:
            # Выбор продолжается по прежнему расходу (раздел 19.7, «Расход окон лимита»).
            logger.warning("llm_usage_credentials_unavailable", error=exc.message)
            return None
        return next(
            (item.auth_index for item in credentials if item.name == account.cliproxy_credential),
            None,
        )

    async def _set_current(self, choice: AccountChoice) -> None:
        task = self._task
        chosen_id = choice.account.id
        if task.current_llm_account_id == chosen_id:
            return
        # Compare-and-swap: аккаунт задачи меняет только её воркер.
        await self._db.execute(
            sa.update(Task)
            .where(
                Task.id == task.id,
                Task.current_llm_account_id.is_not_distinct_from(task.current_llm_account_id),
            )
            .values(current_llm_account_id=chosen_id),
        )
        await self._db.commit()
        await self._db.refresh(task, ["current_llm_account_id"])

    async def _log_switch(self, previous_id: uuid.UUID, choice: AccountChoice) -> None:
        context = {
            "from_account_id": str(previous_id),
            "to_account_id": str(choice.account.id),
            "reason": choice.reason.value,
        }
        logger.info("llm_account_switched", task_id=str(self._task.id), **context)
        await write_app_log(
            level=AppLogLevel.INFO,
            source=_SOURCE,
            message="llm_account_switched",
            context=context,
            task_id=self._task.id,
        )

    async def _notify_all_above_threshold(self) -> None:
        key = _ABOVE_THRESHOLD_PUSH_KEY.format(user_id=self._task.created_by)
        try:
            opened = await self._redis.set(
                key,
                "1",
                nx=True,
                ex=ABOVE_THRESHOLD_PUSH_WINDOW_SECONDS,
            )
        except RedisError:
            logger.warning("push_window_unavailable", push_event="llm_above_threshold")
            opened = True
        if opened:
            await notify_task_event(
                self._db,
                event=NotificationEvent.LLM_ACCOUNTS_ABOVE_THRESHOLD,
                task=self._task,
                detail=(
                    f"{self._task.code}: расход всех LLM-аккаунтов выше порога, "
                    "работа продолжается на наименее израсходованном"
                ),
            )

    async def report_error(self, route: TurnRoute, assistant_error: str | None) -> bool | None:
        """
        Ошибка хода маршрута ``route``. Возвращает, временный ли это сбой для
        задачи: отклонённый вход и лимит — временные, если у автора остался
        другой годный аккаунт; None — ошибка не про аккаунт, классификация обычная.
        """
        if assistant_error == AUTHENTICATION_FAILED:
            await require_login(self._db, route.account_id)
        elif assistant_error == RATE_LIMIT:
            await self._mark_rate_limited(route.account_id, resets_at=None)
        else:
            return None
        has_other = await self._has_active()
        return has_other or assistant_error == RATE_LIMIT

    async def record_rate_limit(self, info: RateLimitInfo) -> None:
        """Событие лимита из потока сессии относится к аккаунту текущего хода."""
        if self.route_in_use is None or info.status != _REJECTED:
            return
        resets_at = datetime.fromtimestamp(info.resets_at, tz=UTC) if info.resets_at else None
        await self._mark_rate_limited(self.route_in_use.account_id, resets_at=resets_at)

    async def _mark_rate_limited(
        self,
        account_id: uuid.UUID,
        *,
        resets_at: datetime | None,
    ) -> None:
        account = await self._db.get(LlmAccount, account_id, populate_existing=True)
        if account is None or account.status is not LlmAccountStatus.ACTIVE:
            return
        account.status = LlmAccountStatus.RATE_LIMITED
        account.rate_limit_resets_at = resets_at or self._clock() + _UNKNOWN_RATE_LIMIT_WINDOW
        await self._db.commit()
        logger.info(
            "llm_account_rate_limited",
            account_id=str(account_id),
            resets_at=account.rate_limit_resets_at,
        )

    async def _has_active(self) -> bool:
        # Аккаунт маршрута к этому моменту уже не `active`.
        stmt = sa.select(LlmAccount.id).where(
            LlmAccount.created_by == self._task.created_by,
            LlmAccount.status == LlmAccountStatus.ACTIVE,
            LlmAccount.default_model.is_not(None),
            LlmAccount.provider.in_(list(PROVIDERS)),
        )
        return await self._db.scalar(stmt.limit(1)) is not None


def _usage_stale(account: LlmAccount, *, now: datetime) -> bool:
    if get_provider(account.provider).usage_source is None:
        return False
    checked_at = account.usage_checked_at
    return checked_at is None or now - checked_at > USAGE_MAX_AGE


def _turn_route(
    account: LlmAccount,
    effort: ReasoningEffort | None,
    *,
    switch_reason: LlmSwitchReason | None,
) -> TurnRoute:
    assert account.default_model is not None
    chosen_effort = effort or account.default_effort
    return TurnRoute(
        account_id=account.id,
        prefix=account.cliproxy_prefix,
        model=account.default_model,
        effort=chosen_effort,
        provider_effort=provider_effort(get_provider(account.provider), chosen_effort),
        switch_reason=switch_reason,
    )


__all__ = ["NoLlmAccountAvailableError", "TaskAccountRouter"]
