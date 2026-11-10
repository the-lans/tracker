"""
Проверки перед запуском и ручными запросами (разделы 3.1, 12.2, 19.7 ТЗ):
стартовый LLM-аккаунт необязателен, но задаче, которой нужен LLM, нужен
доступный аккаунт автора.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from db.models.enums import LlmAccountStatus, NodeType, ScriptLanguage, TaskStatus
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.prompts import TaskLibraryPrompt
from db.models.tasks import Task
from services.errors import ValidationError
from services.manual_queue import enqueue_freeform_prompt_run, enqueue_library_prompt_run
from services.task_launch import (
    LLM_ACCOUNT_UNAVAILABLE,
    PIPELINE_REQUIRED_MESSAGE,
    SESSION_WITHOUT_LLM,
    ensure_llm_account_for_launch,
)
from tests.factories import make_llm_account, make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


async def _task_with_nodes(
    db_session: AsyncSession,
    owner: User,
    nodes: list[tuple[NodeType, bool]],
    *,
    with_llm_account: bool = False,
    status: TaskStatus = TaskStatus.NEW,
) -> Task:
    pipeline = Pipeline(name="p", is_archived=False, created_by=owner.id)
    db_session.add(pipeline)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:6]}",
        title="t",
        description="d",
        created_by=owner.id,
        pipeline_id=pipeline.id,
        status=status,
    )
    if with_llm_account:
        task.llm_account_id = (await make_llm_account(db_session, owner_id=owner.id)).id
    db_session.add(task)
    await db_session.flush()
    for order_index, (node_type, is_enabled) in enumerate(nodes):
        node = Node(
            created_by=owner.id,
            pipeline_id=pipeline.id,
            order_index=order_index,
            name=f"{node_type}-{order_index}",
            node_type=node_type,
            is_library_item=False,
        )
        db_session.add(node)
        await db_session.flush()
        db_session.add(
            TaskNode(
                task_id=task.id,
                node_id=node.id,
                order_index=order_index,
                is_enabled=is_enabled,
            ),
        )
    await db_session.flush()
    return task


class TestEnsureLlmAccountForLaunch:
    @pytest.mark.parametrize(
        "nodes",
        [
            [(NodeType.SCRIPT, True), (NodeType.CLEAR_CONTEXT, True)],
            [(NodeType.SCRIPT, True), (NodeType.PLAIN_PROMPT, False)],
        ],
        ids=["scripts_only", "llm_node_disabled"],
    )
    async def test_allowed_without_account(
        self,
        db_session: AsyncSession,
        nodes: list[tuple[NodeType, bool]],
    ) -> None:
        task = await _task_with_nodes(db_session, await make_user(db_session), nodes)

        await ensure_llm_account_for_launch(db_session, task)

    @pytest.mark.parametrize(
        "node_type",
        [NodeType.PLAIN_PROMPT, NodeType.SLASH_COMMAND, NodeType.PLAN_PROMPT],
    )
    async def test_llm_node_needs_account(
        self,
        db_session: AsyncSession,
        node_type: NodeType,
    ) -> None:
        owner = await make_user(db_session)
        task = await _task_with_nodes(db_session, owner, [(node_type, True)])

        with pytest.raises(ValidationError, match="LLM-аккаунт"):
            await ensure_llm_account_for_launch(db_session, task)

    async def test_parent_summary_needs_account(self, db_session: AsyncSession) -> None:
        task = await _task_with_nodes(db_session, await make_user(db_session), [])
        task.use_parent_summary = True

        with pytest.raises(ValidationError, match="Пересказ"):
            await ensure_llm_account_for_launch(db_session, task)

    async def test_account_present(self, db_session: AsyncSession) -> None:
        owner = await make_user(db_session)
        task = await _task_with_nodes(
            db_session,
            owner,
            [(NodeType.PLAIN_PROMPT, True)],
            with_llm_account=True,
        )

        await ensure_llm_account_for_launch(db_session, task)

    async def test_author_account_without_start(self, db_session: AsyncSession) -> None:
        """Пустой стартовый аккаунт — «Автоматически»: хватает аккаунта автора."""
        owner = await make_user(db_session)
        await make_llm_account(db_session, owner_id=owner.id, status=LlmAccountStatus.RATE_LIMITED)
        task = await _task_with_nodes(db_session, owner, [(NodeType.PLAIN_PROMPT, True)])

        await ensure_llm_account_for_launch(db_session, task)

    @pytest.mark.parametrize(
        ("status", "model", "provider"),
        [
            (LlmAccountStatus.LOGIN_REQUIRED, "claude-opus-5-5", "anthropic"),
            (LlmAccountStatus.DISABLED, "claude-opus-5-5", "anthropic"),
            (LlmAccountStatus.ACTIVE, None, "anthropic"),
            (LlmAccountStatus.ACTIVE, "claude-opus-5-5", "unknown"),
        ],
        ids=["login_required", "disabled", "no_model", "unknown_provider"],
    )
    async def test_unusable_accounts_rejected(
        self,
        db_session: AsyncSession,
        status: LlmAccountStatus,
        model: str | None,
        provider: str,
    ) -> None:
        owner = await make_user(db_session)
        await make_llm_account(
            db_session,
            owner_id=owner.id,
            status=status,
            default_model=model,
            provider=provider,
        )
        task = await _task_with_nodes(db_session, owner, [(NodeType.PLAIN_PROMPT, True)])

        with pytest.raises(ValidationError, match=LLM_ACCOUNT_UNAVAILABLE):
            await ensure_llm_account_for_launch(db_session, task)

    async def test_other_user_account_ignored(self, db_session: AsyncSession) -> None:
        other = await make_user(db_session)
        await make_llm_account(db_session, owner_id=other.id)
        task = await _task_with_nodes(
            db_session,
            await make_user(db_session),
            [(NodeType.PLAIN_PROMPT, True)],
        )

        with pytest.raises(ValidationError, match=LLM_ACCOUNT_UNAVAILABLE):
            await ensure_llm_account_for_launch(db_session, task)


class TestStartApi:
    async def test_llm_node_without_account_rejected(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        task = await _task_with_nodes(db_session, current_user, [(NodeType.PLAIN_PROMPT, True)])

        response = await authed_client.post(f"/tasks/{task.id}/start")

        assert response.status_code == 422
        await db_session.refresh(task)
        assert task.status is TaskStatus.NEW


class TestPipelineRequired:
    """Раздел 13.1: задача без пайплайна не запускается ни кнопкой, ни по API."""

    async def test_start_rejected(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        task = await _task_with_nodes(db_session, current_user, [(NodeType.SCRIPT, True)])
        task.pipeline_id = None
        await db_session.flush()

        response = await authed_client.post(f"/tasks/{task.id}/start")

        assert response.status_code == 422
        assert response.json()["error"]["message"] == PIPELINE_REQUIRED_MESSAGE
        await db_session.refresh(task)
        assert task.status is TaskStatus.NEW


class TestManualRequests:
    @pytest.mark.parametrize(
        ("status", "nodes", "author_account", "error"),
        [
            (TaskStatus.IN_PROGRESS, [NodeType.PLAIN_PROMPT], True, None),
            (TaskStatus.IN_PROGRESS, [NodeType.SCRIPT], True, SESSION_WITHOUT_LLM),
            (TaskStatus.IN_PROGRESS, [NodeType.PLAIN_PROMPT], False, LLM_ACCOUNT_UNAVAILABLE),
            (TaskStatus.REFINING, [], True, None),
            (TaskStatus.REFINING, [], False, LLM_ACCOUNT_UNAVAILABLE),
        ],
        ids=["llm_task", "scripts_only", "no_account", "chat", "chat_no_account"],
    )
    async def test_freeform(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        nodes: list[NodeType],
        author_account: bool,
        error: str | None,
    ) -> None:
        owner = await make_user(db_session)
        if author_account:
            await make_llm_account(db_session, owner_id=owner.id)
        task = await _task_with_nodes(
            db_session,
            owner,
            [(node_type, True) for node_type in nodes],
            status=status,
        )

        enqueue = enqueue_freeform_prompt_run(
            db_session,
            task_id=task.id,
            raw_prompt_text="привет",
            requested_by=task.created_by,
        )
        if error is None:
            await enqueue
        else:
            with pytest.raises(ValidationError, match=error):
                await enqueue


class TestLibraryRequests:
    """Раздел 7.3: промт библиотеки выполняет LLM, скрипт — нет; чату нужен аккаунт всегда."""

    @pytest.mark.parametrize(
        ("status", "node_type", "author_account", "error"),
        [
            (TaskStatus.IN_PROGRESS, NodeType.SCRIPT, True, None),
            (TaskStatus.IN_PROGRESS, NodeType.PLAIN_PROMPT, True, SESSION_WITHOUT_LLM),
            (TaskStatus.REFINING, NodeType.SCRIPT, True, None),
            (TaskStatus.REFINING, NodeType.SCRIPT, False, LLM_ACCOUNT_UNAVAILABLE),
        ],
        ids=["script", "prompt_without_llm", "chat_script", "chat_script_no_account"],
    )
    async def test_enqueue(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        node_type: NodeType,
        author_account: bool,
        error: str | None,
    ) -> None:
        owner = await make_user(db_session)
        if author_account:
            await make_llm_account(db_session, owner_id=owner.id)
        task = await _task_with_nodes(db_session, owner, [(NodeType.SCRIPT, True)], status=status)
        node = Node(
            created_by=owner.id,
            name="library",
            node_type=node_type,
            prompt_template="промт" if node_type is NodeType.PLAIN_PROMPT else None,
            script_content="echo" if node_type is NodeType.SCRIPT else None,
            script_language=ScriptLanguage.BASH if node_type is NodeType.SCRIPT else None,
            is_library_item=True,
        )
        db_session.add(node)
        await db_session.flush()
        task_library_prompt = TaskLibraryPrompt(task_id=task.id, node_id=node.id, added_by=owner.id)
        db_session.add(task_library_prompt)
        await db_session.flush()

        enqueue = enqueue_library_prompt_run(
            db_session,
            task_library_prompt=task_library_prompt,
            node=node,
            requested_by=owner.id,
        )
        if error is None:
            await enqueue
        else:
            with pytest.raises(ValidationError, match=error):
                await enqueue
