"""Выбор модели CI-агента из профиля автора задачи."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from clients.cliproxy import CliproxyManagementClient
from services import test_agent
from tests.factories import make_llm_account
from tests.test_plan_mode import _non_closing_session_factory

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User
    from tests.cliproxy_support import FakeCliproxy


class TestCiAgentModelRoute:
    async def test_route_uses_updated_profile_model(
        self,
        db_session: AsyncSession,
        current_user: User,
        fake_cliproxy: FakeCliproxy,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        @asynccontextmanager
        async def proxy() -> AsyncIterator[CliproxyManagementClient]:
            yield fake_cliproxy.client()

        monkeypatch.setattr(test_agent, "open_cliproxy_client", proxy)
        current_user.ci_agent_model = "custom-ci-model"
        account = await make_llm_account(
            db_session,
            owner_id=current_user.id,
            provider="openai",
            credential="ci-model.json",
        )
        fake_cliproxy.add_credential(
            "ci-model.json", provider="openai", models=["custom-ci-model", "second-ci-model"]
        )
        await db_session.commit()
        monkeypatch.setattr(
            test_agent, "async_session_factory", _non_closing_session_factory(db_session)
        )
        route = await test_agent.ci_agent_route(current_user.id)
        assert route.account_id == account.id
        assert route.model == "custom-ci-model"
        current_user.ci_agent_model = "second-ci-model"
        await db_session.commit()
        route = await test_agent.ci_agent_route(current_user.id)
        assert route.model == "second-ci-model"
