"""
Раздел 19.4, правило 8: значения секретных переменных не показываются — ни в
предпросмотре промта, ни в `node_logs.rendered_prompt`, а в сессию уходит
настоящее значение. Переменные уровня задачи скрыты всегда.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import EnvVariableScope, NodeType
from db.models.env_vars import EnvVariable, TaskEnvVariable
from services.crypto import encrypt
from services.pipeline_orchestrator import run_pipeline
from services.template_context import SECRET_MASK, render_for_task
from tests.fakes import FakeClaudeAgentClient, make_result_message
from tests.test_pipeline_orchestrator import (
    _add_node,
    _make_task_with_pipeline,
    _node_logs_for,
)

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


def _global(key: str, value: str, *, is_secret: bool) -> EnvVariable:
    return EnvVariable(
        key=key,
        value_encrypted=encrypt(value),
        is_secret=is_secret,
        scope=EnvVariableScope.GLOBAL,
    )


class TestRender:
    @pytest.mark.parametrize(
        ("is_secret", "shown"),
        [(True, SECRET_MASK), (False, "value-1")],
        ids=["secret", "plain"],
    )
    async def test_global_variable(
        self,
        db_session: AsyncSession,
        is_secret: bool,
        shown: str,
    ) -> None:
        task = await _make_task_with_pipeline(db_session)
        db_session.add(_global("API_KEY", "value-1", is_secret=is_secret))
        await db_session.flush()

        rendered = await render_for_task(db_session, task, "key={{env.API_KEY}}")

        assert rendered.text == "key=value-1"
        assert rendered.display == f"key={shown}"

    async def test_task_variable_always_masked(self, db_session: AsyncSession) -> None:
        task = await _make_task_with_pipeline(db_session)
        db_session.add(TaskEnvVariable(task_id=task.id, key="TOKEN", value_encrypted=encrypt("t")))
        await db_session.flush()

        rendered = await render_for_task(db_session, task, "{{env.TOKEN}}")

        assert (rendered.text, rendered.display) == ("t", SECRET_MASK)


class TestPreview:
    async def test_user_sees_mask(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        task = await _make_task_with_pipeline(db_session)
        task.created_by = current_user.id
        db_session.add(_global("DEPLOY_TOKEN", "deploy-secret", is_secret=True))
        await db_session.flush()

        response = await authed_client.post(
            "/templates/preview",
            json={"text": "{{env.DEPLOY_TOKEN}}", "scope": "freeform", "task_id": str(task.id)},
        )

        assert response.json()["rendered_text"] == SECRET_MASK


class TestNodeLog:
    async def test_session_gets_value_log_gets_mask(
        self,
        db_session: AsyncSession,
        tmp_path: Path,
    ) -> None:
        task = await _make_task_with_pipeline(db_session)
        db_session.add(_global("DEPLOY_TOKEN", "deploy-secret", is_secret=True))
        await _add_node(
            db_session,
            task,
            order_index=0,
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="token {{env.DEPLOY_TOKEN}}",
        )
        client = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])

        await run_pipeline(
            db_session,
            task=task,
            claude_session=ClaudeCodeSession(client),
            repos_path=tmp_path,
        )

        assert client.queries == ["token deploy-secret"]
        node_log = (await _node_logs_for(db_session, task.id))[0]
        assert node_log.rendered_prompt == f"token {SECRET_MASK}"
