"""
Аккаунт хода сессии задачи (раздел 19.7 ТЗ).

Перед каждым обращением к сессии воркер спрашивает `TaskAccountRouter.route`:
роутер обновляет расход прежнего аккаунта задачи, если опрос устарел,
собирает нагрузку аккаунтов автора и выбирает аккаунт правилом
`services/llm_account_choice.choose_account` под блокировкой
`llm-route:<user_id>`. Первый ход на свободном аккаунте записывает старт его
окна (`window_started_at`, compare-and-swap). Затем роутер публикует маршрут
для `llm-gateway` и выставляет `tasks.current_llm_account_id`; смена аккаунта
пишется событием `llm_account_switched`. `limit_gate` — та же оценка без
побочных эффектов: время ожидания сброса, если все аккаунты на пороге.

Ошибка хода, в которой провайдер отклонил вход или исчерпан лимит, переводит
аккаунт маршрута в `login_required`/`rate_limited` (`report_error`); повтор
ноды выберет аккаунт заново.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import sqlalchemy as sa

from app_logging.app_logs import write_app_log
from app_logging.config import get_logger
from db.models.enums import (
    AppLogLevel,
    LlmAccountStatus,
    LlmSwitchReason,
    NodeLogStatus,
    NodeType,
    ReasoningEffort,
    TaskStatus,
)
from db.models.llm import LlmAccount
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import User
from services.distributed_lock import wait_for_lock
from services.errors import ExternalServiceError
from services.llm_account_checks import require_login
from services.llm_account_choice import (
    FIVE_HOUR_WINDOW,
    AccountChoice,
    AccountView,
    ChoiceRequest,
    LimitWait,
    LlmLimitWaitError,
    NoLlmAccountAvailableError,
    choose_account,
    wait_until,
)
from services.llm_providers import PROVIDERS, get_provider, provider_effort
from services.llm_routing import TurnRoute, publish_route
from services.llm_usage import (
    UNKNOWN_RATE_LIMIT_WINDOW,
    refresh_account_usage,
    turns_since_usage_check,
)

if TYPE_CHECKING:
    from claude_agent_sdk import RateLimitInfo
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from clients.cliproxy import CliproxyManagementClient

logger = get_logger("account_router")

_SOURCE = "account_router"
# Раздел 19.7: перед выбором расход обновляется, если опрос старше минуты.
USAGE_MAX_AGE = timedelta(seconds=60)
# Раздел 19.7: выбор по одному пользователю — под блокировкой, чтобы
# параллельные задачи не открыли два окна разом. Выбор занимает доли секунды;
# не дождавшись, ход выбирает без блокировки, а не падает.
ROUTE_LOCK_KEY = "llm-route:{user_id}"
ROUTE_LOCK_TTL_SECONDS = 30
ROUTE_LOCK_WAIT_SECONDS = 10.0
# Задачи автора, которым сейчас нужен аккаунт: нагрузка окон и число задач в работе.
IN_WORK_STATUSES = (TaskStatus.IN_PROGRESS, TaskStatus.REFINING, TaskStatus.REBASE_CONFLICT)
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
        boundary: bool = True,
    ) -> TurnRoute:
        """
        Маршрут хода: аккаунт, модель и уровень рассуждений. Все аккаунты
        исключены — `NoLlmAccountAvailableError`; все на пороге или
        исчерпаны — `LlmLimitWaitError` (п. 5 раздела 19.7).
        """
        task = self._task
        lock_key = ROUTE_LOCK_KEY.format(user_id=task.created_by)
        async with wait_for_lock(
            self._redis,
            lock_key,
            ttl_seconds=ROUTE_LOCK_TTL_SECONDS,
            wait_seconds=ROUTE_LOCK_WAIT_SECONDS,
        ):
            views, request = await self._prepare(node_type=node_type, boundary=boundary)
            choice = choose_account(views, request)
            if isinstance(choice, LimitWait):
                raise LlmLimitWaitError(choice.until)
            if choice.opens_window:
                await self._open_window(choice.account, now=request.now)
            previous_id = await self._previous_account_id()
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
        self.route_in_use = route
        return route

    async def limit_gate(
        self,
        *,
        node_type: NodeType | None = None,
        boundary: bool = True,
    ) -> datetime | None:
        """
        Ворота лимита перед ходом (раздел 19.7, «Ожидание лимита»): до какого
        времени ход ждать сброса; None — ход можно начинать. Без выбора и
        маршрута: окно не открывается, аккаунт задачи не меняется.
        """
        views, request = await self._prepare(node_type=node_type, boundary=boundary)
        return wait_until(views, request)

    async def _prepare(
        self,
        *,
        node_type: NodeType | None,
        boundary: bool,
    ) -> tuple[list[AccountView], ChoiceRequest]:
        task = self._task
        await self._db.refresh(task, ["current_llm_account_id", "llm_account_id"])
        accounts = await self._accounts()
        # Расход обновляется у аккаунта, который останется при выборе: текущего или стартового.
        kept_id = task.current_llm_account_id or task.llm_account_id
        await self._refresh_stale_usage(accounts, kept_id)
        views = await self._views(accounts)
        request = ChoiceRequest(
            now=self._clock(),
            threshold_pct=await self._threshold(),
            current_id=task.current_llm_account_id,
            start_id=task.llm_account_id,
            plan_prompt=node_type is NodeType.PLAN_PROMPT,
            boundary=boundary,
            tasks_in_work=await self._tasks_in_work(),
        )
        return views, request

    async def _previous_account_id(self) -> uuid.UUID | None:
        """
        Аккаунт предыдущего обращения задачи (раздел 15.2): текущий, а после
        сброса текущего («Вернуть в новые», смена стартового) — аккаунт её
        последнего хода; у задачи без ходов — стартовый.
        """
        task = self._task
        if task.current_llm_account_id is not None:
            return task.current_llm_account_id
        last_turn = (
            sa.select(NodeLog.llm_account_id)
            .where(
                NodeLog.task_id == task.id,
                NodeLog.llm_account_id.is_not(None),
                NodeLog.started_at.is_not(None),
            )
            .order_by(NodeLog.started_at.desc())
            .limit(1)
        )
        return await self._db.scalar(last_turn) or task.llm_account_id

    async def _accounts(self) -> list[LlmAccount]:
        stmt = (
            sa.select(LlmAccount)
            .where(LlmAccount.created_by == self._task.created_by)
            .order_by(LlmAccount.switch_order)
            .execution_options(populate_existing=True)
        )
        return list((await self._db.execute(stmt)).scalars())

    async def _threshold(self) -> int:
        author = await self._db.get(User, self._task.created_by)
        assert author is not None
        return author.llm_switch_threshold_5h_pct

    async def _views(self, accounts: Sequence[LlmAccount]) -> list[AccountView]:
        """Нагрузка аккаунтов: задачи в работе на них и идущие ходы других задач."""
        task = self._task
        tasks_stmt = (
            sa.select(Task.current_llm_account_id, sa.func.count(Task.id))
            .where(
                Task.created_by == task.created_by,
                Task.status.in_(IN_WORK_STATUSES),
                Task.current_llm_account_id.is_not(None),
            )
            .group_by(Task.current_llm_account_id)
        )
        turns_stmt = (
            sa.select(NodeLog.llm_account_id, sa.func.count(NodeLog.id))
            .where(
                NodeLog.status == NodeLogStatus.RUNNING,
                NodeLog.task_id != task.id,
                NodeLog.llm_account_id.in_([account.id for account in accounts]),
            )
            .group_by(NodeLog.llm_account_id)
        )
        tasks = {key: count for key, count in await self._db.execute(tasks_stmt)}
        turns = {key: count for key, count in await self._db.execute(turns_stmt)}
        return [
            AccountView(
                account,
                tasks=tasks.get(account.id, 0),
                running_turns=turns.get(account.id, 0),
            )
            for account in accounts
        ]

    async def _tasks_in_work(self) -> int:
        """Задачи автора в работе; выбирающая задача — среди них, в каком бы статусе ни была."""
        task = self._task
        stmt = sa.select(sa.func.count(Task.id)).where(
            Task.created_by == task.created_by,
            Task.status.in_(IN_WORK_STATUSES),
            Task.id != task.id,
        )
        return int(await self._db.scalar(stmt) or 0) + 1

    async def _open_window(self, account: LlmAccount, *, now: datetime) -> None:
        """
        Старт 5-часового окна свободного аккаунта: compare-and-swap, чтобы
        окно, уже открытое другой задачей, не сдвигалось.
        """
        opened = await self._db.scalar(
            sa.update(LlmAccount)
            .where(
                LlmAccount.id == account.id,
                sa.or_(
                    LlmAccount.window_started_at.is_(None),
                    LlmAccount.window_started_at <= now - FIVE_HOUR_WINDOW,
                ),
            )
            .values(window_started_at=now)
            .returning(LlmAccount.id),
        )
        await self._db.commit()
        if opened is not None:
            logger.info(
                "llm_window_opened",
                account_id=str(account.id),
                task_id=str(self._task.id),
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
            turns=await turns_since_usage_check(self._db, account),
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
        account.rate_limit_resets_at = resets_at or self._clock() + UNKNOWN_RATE_LIMIT_WINDOW
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


__all__ = ["LlmLimitWaitError", "NoLlmAccountAvailableError", "TaskAccountRouter"]
