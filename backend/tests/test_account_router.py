"""Аккаунт хода сессии задачи: выбор, маршрут, переключение и ошибки (раздел 19.7 ТЗ)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from claude_agent_sdk import RateLimitInfo

from db.models.enums import (
    LlmAccountStatus,
    LlmSwitchReason,
    NodeLogStatus,
    NodeLogTriggerType,
    NodeType,
    ReasoningEffort,
    TaskStatus,
)
from db.models.llm import LlmAccount
from db.models.logs import NodeLog
from db.models.tasks import Task
from services import account_router as account_router_module
from services.account_router import ROUTE_LOCK_KEY, TaskAccountRouter
from services.llm_account_choice import LlmLimitWaitError, NoLlmAccountAvailableError
from services.llm_routing import TurnRoute, read_route
from services.notifications import NotificationEvent
from tests.cliproxy_support import FakeCliproxy
from tests.factories import make_llm_account, make_task, make_user

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_LIMITED = LlmAccountStatus.RATE_LIMITED


class Recorded:
    def __init__(self) -> None:
        self.app_logs: list[dict[str, Any]] = []
        self.pushes: list[tuple[NotificationEvent, uuid.UUID]] = []


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> Recorded:
    """Записи `app_logs` и push-уведомления роутера (адресат — задача или пользователь)."""
    sink = Recorded()

    async def app_log(**kwargs: Any) -> None:
        sink.app_logs.append(kwargs)

    async def task_push(
        _db: AsyncSession,
        *,
        event: NotificationEvent,
        task: Task,
        **_: Any,
    ) -> None:
        sink.pushes.append((event, task.id))

    async def user_push(
        _db: AsyncSession,
        *,
        event: NotificationEvent,
        user_id: uuid.UUID,
        **_: Any,
    ) -> None:
        sink.pushes.append((event, user_id))

    monkeypatch.setattr(account_router_module, "write_app_log", app_log)
    monkeypatch.setattr("services.llm_account_checks.notify_user_event", user_push)
    monkeypatch.setattr("services.llm_usage.write_app_log", app_log)
    return sink


class Setup:
    def __init__(self, db_session: AsyncSession, fake_cliproxy: FakeCliproxy) -> None:
        self.db_session = db_session
        self.fake_cliproxy = fake_cliproxy
        self.owner_id = uuid.uuid4()

    async def owner(self) -> uuid.UUID:
        user = await make_user(self.db_session)
        user.llm_switch_threshold_5h_pct = 93
        await self.db_session.flush()
        self.owner_id = user.id
        return user.id

    async def account(
        self,
        *,
        provider: str = "anthropic",
        pct_5h: str | None = None,
        status: LlmAccountStatus = LlmAccountStatus.ACTIVE,
        checked_at: datetime | None = _NOW,
        resets_in: timedelta | None = None,
        started_ago: timedelta | None = None,
    ) -> LlmAccount:
        credential = f"{uuid.uuid4().hex}@example.com.json"
        account = await make_llm_account(
            self.db_session,
            owner_id=self.owner_id,
            provider=provider,
            credential=credential,
            default_model="claude-opus-5-5" if provider == "anthropic" else "gpt-6-sol",
            status=status,
        )
        account.usage_5h_pct = Decimal(pct_5h) if pct_5h else None
        account.usage_checked_at = checked_at
        account.usage_5h_resets_at = _NOW + resets_in if resets_in is not None else None
        account.window_started_at = _NOW - started_ago if started_ago is not None else None
        account.rate_limit_resets_at = _NOW + timedelta(hours=1) if status is _LIMITED else None
        await self.db_session.flush()
        self.fake_cliproxy.add_credential(credential)
        return account

    async def task(
        self,
        start: LlmAccount | None,
        current: LlmAccount | None = None,
        status: TaskStatus = TaskStatus.IN_PROGRESS,
    ) -> Task:
        return await make_task(
            self.db_session,
            created_by=self.owner_id,
            llm_account_id=start.id if start else None,
            current_llm_account_id=current.id if current else None,
            status=status,
        )


@pytest.fixture
async def setup(db_session: AsyncSession, fake_cliproxy: FakeCliproxy) -> Setup:
    result = Setup(db_session, fake_cliproxy)
    await result.owner()
    return result


def _router(
    db_session: AsyncSession,
    redis_client: Redis,
    fake_cliproxy: FakeCliproxy,
    task: Task,
) -> TaskAccountRouter:
    return TaskAccountRouter(
        db_session=db_session,
        redis_client=redis_client,
        task=task,
        cliproxy=fake_cliproxy.client(),
        clock=lambda: _NOW,
    )


@pytest.mark.usefixtures("recorded")
class TestRoute:
    async def test_first_turn_on_start_account(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        recorded: Recorded,
    ) -> None:
        await setup.account()
        start = await setup.account()
        task = await setup.task(start)

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=NodeType.PLAIN_PROMPT,
        )

        assert route == TurnRoute(
            account_id=start.id,
            prefix=start.cliproxy_prefix,
            model="claude-opus-5-5",
            effort=ReasoningEffort.HIGH,
            provider_effort=ReasoningEffort.HIGH,
        )
        assert await read_route(redis_client, task.id) == route
        assert task.current_llm_account_id == start.id
        assert recorded.app_logs == []

    async def test_node_effort_translated_for_provider(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        codex = await setup.account(provider="openai")
        task = await setup.task(codex)

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=ReasoningEffort.MAX,
            node_type=NodeType.PLAIN_PROMPT,
        )

        assert (route.effort, route.provider_effort) == (ReasoningEffort.MAX, ReasoningEffort.XHIGH)

    async def test_switch_over_threshold_logged(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        recorded: Recorded,
    ) -> None:
        current = await setup.account(pct_5h="93")
        spare = await setup.account(pct_5h="10")
        task = await setup.task(current, current=current)

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=None,
        )

        assert (route.account_id, route.switch_reason) == (spare.id, LlmSwitchReason.THRESHOLD_5H)
        await db_session.refresh(task)
        await db_session.refresh(spare)
        assert task.current_llm_account_id == spare.id
        assert spare.window_started_at == _NOW
        assert [(entry["message"], entry["context"]) for entry in recorded.app_logs] == [
            (
                "llm_account_switched",
                {
                    "from_account_id": str(current.id),
                    "to_account_id": str(spare.id),
                    "reason": "threshold_5h",
                },
            ),
        ]
        assert recorded.pushes == []

    @pytest.mark.parametrize(
        ("turns", "switched"),
        [
            ([], False),
            (["start"], False),
            (["other"], True),
            (["start", "other"], True),
            (["other", "start"], False),
        ],
        ids=["no_turns", "last_on_start", "last_on_other", "latest_wins", "back_on_start"],
    )
    async def test_after_reset_compared_with_last_turn(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        recorded: Recorded,
        turns: list[str],
        switched: bool,
    ) -> None:
        other = await setup.account()
        start = await setup.account()
        task = await setup.task(start)
        accounts = {"start": start, "other": other}
        for minute, name in enumerate(turns):
            db_session.add(
                NodeLog(
                    task_id=task.id,
                    trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
                    status=NodeLogStatus.SUCCESS,
                    llm_account_id=accounts[name].id,
                    started_at=_NOW - timedelta(minutes=10 - minute),
                ),
            )
        # Ход без времени начала не считается последним.
        db_session.add(
            NodeLog(
                task_id=task.id,
                trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
                llm_account_id=other.id,
            ),
        )
        await db_session.flush()

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=None,
        )

        assert route.account_id == start.id
        assert route.switch_reason == (LlmSwitchReason.START if switched else None)
        assert len(recorded.app_logs) == (1 if switched else 0)

    @pytest.mark.parametrize(
        ("checked_at", "polled"),
        [(None, True), (_NOW - timedelta(seconds=61), True), (_NOW - timedelta(seconds=30), False)],
        ids=["never", "stale", "fresh"],
    )
    async def test_stale_usage_refreshed_before_choice(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        checked_at: datetime | None,
        polled: bool,
    ) -> None:
        fake_cliproxy.api_responses[_USAGE_URL] = (
            200,
            json.dumps({"five_hour": {"utilization": 97}, "seven_day": None}),
        )
        current = await setup.account(pct_5h="40", checked_at=checked_at)
        spare = await setup.account()
        task = await setup.task(current, current=current)

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=None,
        )

        assert len(fake_cliproxy.api_calls) == int(polled)
        assert route.account_id == (spare.id if polled else current.id)

    @pytest.mark.parametrize("down", [True, False], ids=["proxy_down", "usage_error"])
    async def test_failed_poll_keeps_choice(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        down: bool,
    ) -> None:
        current = await setup.account(pct_5h="40", checked_at=None)
        task = await setup.task(current, current=current)
        router = _router(db_session, redis_client, fake_cliproxy, task)
        fake_cliproxy.down = down

        route = await router.route(effort=None, node_type=None)

        assert route.account_id == current.id

    async def test_all_at_threshold_waits(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        current = await setup.account(pct_5h="99", resets_in=timedelta(hours=2))
        await setup.account(status=_LIMITED)
        task = await setup.task(current, current=current)

        with pytest.raises(LlmLimitWaitError) as raised:
            await _router(db_session, redis_client, fake_cliproxy, task).route(
                effort=None,
                node_type=None,
            )

        assert raised.value.until == _NOW + timedelta(hours=1)
        assert await read_route(redis_client, task.id) is None
        await db_session.refresh(task)
        assert task.current_llm_account_id == current.id

    async def test_plan_prompt_skips_unverified_provider(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        google = await setup.account(provider="google")
        claude = await setup.account()
        task = await setup.task(google, current=google)

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=NodeType.PLAN_PROMPT,
        )

        assert route.account_id == claude.id

    async def test_no_active_account(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        disabled = await setup.account(status=LlmAccountStatus.DISABLED)
        task = await setup.task(disabled)

        with pytest.raises(NoLlmAccountAvailableError):
            await _router(db_session, redis_client, fake_cliproxy, task).route(
                effort=None,
                node_type=None,
            )

        assert await read_route(redis_client, task.id) is None

    async def test_other_users_accounts_ignored(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        own = await setup.account(pct_5h="99")
        task = await setup.task(own, current=own)
        await setup.owner()
        await setup.account()

        with pytest.raises(LlmLimitWaitError):
            await _router(db_session, redis_client, fake_cliproxy, task).route(
                effort=None,
                node_type=None,
            )


@pytest.mark.usefixtures("recorded")
class TestWindows:
    @pytest.mark.parametrize(
        ("started_ago", "expected"),
        [(timedelta(hours=2), "running"), (timedelta(hours=3), "free")],
        ids=["step_ahead", "step_passed"],
    )
    async def test_second_task_staggered(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        started_ago: timedelta,
        expected: str,
    ) -> None:
        running = await setup.account(started_ago=started_ago)
        free = await setup.account()
        await setup.task(running, current=running)
        await setup.task(None, current=running, status=TaskStatus.PAUSED)
        task = await setup.task(None)
        accounts = {"running": running, "free": free}

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=None,
        )

        assert route.account_id == accounts[expected].id
        await db_session.refresh(free)
        assert free.window_started_at == (_NOW if expected == "free" else None)

    async def test_open_window_not_moved(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        account = await setup.account()
        task = await setup.task(account)
        # Другая задача открыла окно между выбором и записью старта.
        await db_session.execute(
            sa.update(LlmAccount)
            .where(LlmAccount.id == account.id)
            .values(window_started_at=_NOW - timedelta(minutes=1)),
        )
        router = _router(db_session, redis_client, fake_cliproxy, task)

        await router._open_window(account, now=_NOW)

        await db_session.refresh(account)
        assert account.window_started_at == _NOW - timedelta(minutes=1)

    async def test_lock_released(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        account = await setup.account()
        task = await setup.task(account)

        await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=None,
        )

        assert await redis_client.get(ROUTE_LOCK_KEY.format(user_id=setup.owner_id)) is None

    async def test_busy_lock_waited_out(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(account_router_module, "ROUTE_LOCK_WAIT_SECONDS", 0.1)
        key = ROUTE_LOCK_KEY.format(user_id=setup.owner_id)
        await redis_client.set(key, "other", ex=60)
        account = await setup.account()
        task = await setup.task(account)

        route = await _router(db_session, redis_client, fake_cliproxy, task).route(
            effort=None,
            node_type=None,
        )

        assert route.account_id == account.id
        assert await redis_client.get(key) in {b"other", "other"}


class TestLimitGate:
    @pytest.mark.parametrize(
        ("spare_status", "expected"),
        [(_LIMITED, _NOW + timedelta(hours=1)), (LlmAccountStatus.ACTIVE, None)],
        ids=["all_blocked", "spare_free"],
    )
    async def test_gate(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        spare_status: LlmAccountStatus,
        expected: datetime | None,
    ) -> None:
        current = await setup.account(pct_5h="95", resets_in=timedelta(hours=3))
        spare = await setup.account(status=spare_status)
        task = await setup.task(current, current=current)

        until = await _router(db_session, redis_client, fake_cliproxy, task).limit_gate()

        assert until == expected
        await db_session.refresh(spare)
        await db_session.refresh(task)
        assert (spare.window_started_at, task.current_llm_account_id) == (None, current.id)
        assert await read_route(redis_client, task.id) is None


@pytest.mark.usefixtures("recorded")
class TestReportError:
    async def _routed(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        *,
        with_spare: bool,
    ) -> tuple[TaskAccountRouter, TurnRoute, LlmAccount]:
        account = await setup.account()
        if with_spare:
            await setup.account()
        task = await setup.task(account)
        router = _router(db_session, redis_client, fake_cliproxy, task)
        return router, await router.route(effort=None, node_type=None), account

    @pytest.mark.parametrize(
        ("error", "with_spare", "transient", "status"),
        [
            ("authentication_failed", True, True, LlmAccountStatus.LOGIN_REQUIRED),
            ("authentication_failed", False, False, LlmAccountStatus.LOGIN_REQUIRED),
            ("rate_limit", True, True, LlmAccountStatus.RATE_LIMITED),
            ("rate_limit", False, True, LlmAccountStatus.RATE_LIMITED),
            ("server_error", True, None, LlmAccountStatus.ACTIVE),
            (None, True, None, LlmAccountStatus.ACTIVE),
        ],
    )
    async def test_account_status_and_transient(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        error: str | None,
        with_spare: bool,
        transient: bool | None,
        status: LlmAccountStatus,
    ) -> None:
        router, route, account = await self._routed(
            db_session,
            redis_client,
            fake_cliproxy,
            setup,
            with_spare=with_spare,
        )

        assert await router.report_error(route, error) is transient

        await db_session.refresh(account)
        assert account.status is status

    async def test_login_required_pushed_once(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        recorded: Recorded,
    ) -> None:
        router, route, _account = await self._routed(
            db_session,
            redis_client,
            fake_cliproxy,
            setup,
            with_spare=True,
        )

        await router.report_error(route, "authentication_failed")
        await router.report_error(route, "authentication_failed")

        assert recorded.pushes == [(NotificationEvent.LLM_LOGIN_REQUIRED, setup.owner_id)]

    async def test_rate_limit_without_reset_time(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        router, route, account = await self._routed(
            db_session,
            redis_client,
            fake_cliproxy,
            setup,
            with_spare=False,
        )

        await router.report_error(route, "rate_limit")

        await db_session.refresh(account)
        assert account.rate_limit_resets_at == _NOW + timedelta(hours=1)


@pytest.mark.usefixtures("recorded")
class TestRateLimitEvent:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [("rejected", LlmAccountStatus.RATE_LIMITED), ("allowed", LlmAccountStatus.ACTIVE)],
    )
    async def test_marks_account_of_current_turn(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
        status: str,
        expected: LlmAccountStatus,
    ) -> None:
        current = await setup.account(pct_5h="99")
        spare = await setup.account()
        task = await setup.task(current, current=current)
        router = _router(db_session, redis_client, fake_cliproxy, task)
        await router.route(effort=None, node_type=None)

        await router.record_rate_limit(
            RateLimitInfo(status=status, resets_at=1_900_000_000),  # type: ignore[arg-type]
        )

        await db_session.refresh(spare)
        await db_session.refresh(current)
        assert (spare.status, current.status) == (expected, LlmAccountStatus.ACTIVE)
        if expected is LlmAccountStatus.RATE_LIMITED:
            assert spare.rate_limit_resets_at == datetime.fromtimestamp(1_900_000_000, tz=UTC)

    async def test_before_first_turn_ignored(
        self,
        db_session: AsyncSession,
        redis_client: Redis,
        fake_cliproxy: FakeCliproxy,
        setup: Setup,
    ) -> None:
        account = await setup.account()
        task = await setup.task(account)

        await _router(db_session, redis_client, fake_cliproxy, task).record_rate_limit(
            RateLimitInfo(status="rejected"),
        )

        await db_session.refresh(account)
        assert account.status is LlmAccountStatus.ACTIVE
