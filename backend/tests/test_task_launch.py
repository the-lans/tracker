"""
Проверки перед запуском (раздел 3.1, 12.2 ТЗ, решение №19 плана): задача
без LLM-аккаунта запускается, только если ей не нужна сессия Claude Code.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from db.models.enums import NodeType, TaskStatus
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.tasks import Task
from services.errors import ValidationError
from services.manual_queue import enqueue_freeform_prompt_run
from services.task_launch import ensure_llm_account_for_launch
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


class TestManualRequests:
    async def test_freeform_without_account_rejected(self, db_session: AsyncSession) -> None:
        task = await _task_with_nodes(db_session, await make_user(db_session), [])

        with pytest.raises(ValidationError, match="LLM-аккаунт"):
            await enqueue_freeform_prompt_run(
                db_session,
                task_id=task.id,
                raw_prompt_text="привет",
                requested_by=task.created_by,
            )
