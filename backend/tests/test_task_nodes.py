"""
Тесты `services/task_nodes.py` — правила редактирования состава нод задачи
и своих промтов (раздел 13.1, 13.2 ТЗ, правило 11 CLAUDE.md).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
import sqlalchemy as sa

from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType, TaskStatus, UserRole
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.tasks import Task
from db.models.users import User
from services.errors import ConflictError, NotFoundError, ValidationError
from services.task_creation import TaskDraft
from services.task_duplication import duplicate_task
from services.task_nodes import (
    CustomNodeDraft,
    add_custom_task_node,
    bind_pipeline_to_task,
    delete_custom_task_node,
    list_task_nodes,
    set_task_node_enabled,
    set_task_node_pause_after,
    update_custom_task_node,
)
from services.task_status import reset_task_to_new

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _make_task_with_nodes(
    db_session: AsyncSession,
    *,
    status: TaskStatus,
    last_failed_order_index: int | None = None,
    node_count: int = 3,
) -> tuple[Task, list[TaskNode]]:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    db_session.add(user)
    await db_session.flush()
    pipeline = Pipeline(name="p", is_archived=False, created_by=user.id)
    db_session.add(pipeline)
    await db_session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="t",
        description="d",
        created_by=user.id,
        pipeline_id=pipeline.id,
        status=status,
        last_failed_order_index=last_failed_order_index,
    )
    db_session.add(task)
    await db_session.flush()
    task_nodes = []
    for order_index in range(node_count):
        node = Node(
            created_by=user.id,
            pipeline_id=pipeline.id,
            order_index=order_index,
            name=f"node-{order_index}",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="x",
            timeout_seconds=60,
            max_retries=1,
            retry_base_delay_seconds=0,
            is_skipped=False,
            is_library_item=False,
            is_archived=False,
        )
        db_session.add(node)
        await db_session.flush()
        task_node = TaskNode(task_id=task.id, node_id=node.id, order_index=order_index)
        db_session.add(task_node)
        task_nodes.append(task_node)
    await db_session.flush()
    return task, task_nodes


async def test_new_task_allows_toggling_any_node(db_session: AsyncSession) -> None:
    task, task_nodes = await _make_task_with_nodes(db_session, status=TaskStatus.NEW)

    for task_node in task_nodes:
        await set_task_node_enabled(
            db_session,
            task=task,
            task_node_id=task_node.id,
            is_enabled=False,
        )

    views = await list_task_nodes(db_session, task)
    assert [view.is_enabled for view in views] == [False, False, False]
    assert [view.editable for view in views] == [True, True, True]
    assert [view.name for view in views] == ["node-0", "node-1", "node-2"]


async def test_failed_task_allows_only_nodes_after_failure_point(
    db_session: AsyncSession,
) -> None:
    task, task_nodes = await _make_task_with_nodes(
        db_session,
        status=TaskStatus.FAILED,
        last_failed_order_index=1,
    )

    await set_task_node_enabled(
        db_session,
        task=task,
        task_node_id=task_nodes[2].id,
        is_enabled=False,
    )
    for locked in task_nodes[:2]:
        with pytest.raises(ConflictError, match="уже выполнялась"):
            await set_task_node_enabled(
                db_session,
                task=task,
                task_node_id=locked.id,
                is_enabled=False,
            )

    views = await list_task_nodes(db_session, task)
    assert [view.editable for view in views] == [False, False, True]
    assert [view.is_enabled for view in views] == [True, True, False]


@pytest.mark.parametrize(
    "status",
    [TaskStatus.QUEUED, TaskStatus.IN_PROGRESS, TaskStatus.PAUSED, TaskStatus.DONE],
)
async def test_started_task_locks_all_nodes(
    db_session: AsyncSession,
    status: TaskStatus,
) -> None:
    task, task_nodes = await _make_task_with_nodes(db_session, status=status, node_count=1)

    with pytest.raises(ConflictError, match="только до запуска"):
        await set_task_node_enabled(
            db_session,
            task=task,
            task_node_id=task_nodes[0].id,
            is_enabled=False,
        )


async def test_node_of_another_task_is_not_found(db_session: AsyncSession) -> None:
    task, _ = await _new_task(db_session, 1)
    _other_task, other_nodes = await _make_task_with_nodes(
        db_session,
        status=TaskStatus.NEW,
        node_count=1,
    )

    with pytest.raises(NotFoundError):
        await set_task_node_enabled(
            db_session,
            task=task,
            task_node_id=other_nodes[0].id,
            is_enabled=False,
        )


class TestPauseAfter:
    """Раздел 13.2: отметка «пауза после» — не состав нод, меняется в любом статусе."""

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_toggled_in_any_status(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
    ) -> None:
        task, task_nodes = await _make_task_with_nodes(
            db_session,
            status=status,
            last_failed_order_index=0 if status is TaskStatus.FAILED else None,
            node_count=2,
        )

        await set_task_node_pause_after(
            db_session,
            task=task,
            task_node_id=task_nodes[0].id,
            pause_after=True,
        )

        views = await list_task_nodes(db_session, task)
        assert [view.pause_after for view in views] == [True, False]
        assert [view.is_enabled for view in views] == [True, True]

    async def test_node_of_another_task_is_not_found(self, db_session: AsyncSession) -> None:
        task, _ = await _new_task(db_session, 1)
        _other, other_nodes = await _make_task_with_nodes(
            db_session,
            status=TaskStatus.NEW,
            node_count=1,
        )

        with pytest.raises(NotFoundError):
            await set_task_node_pause_after(
                db_session,
                task=task,
                task_node_id=other_nodes[0].id,
                pause_after=True,
            )


_PROMPT = CustomNodeDraft(
    name="Уточнения",
    node_type=NodeType.PLAIN_PROMPT,
    prompt_template="Задай вопросы",
)


async def _new_task(db_session: AsyncSession, node_count: int) -> tuple[Task, list[TaskNode]]:
    return await _make_task_with_nodes(db_session, status=TaskStatus.NEW, node_count=node_count)


async def _names(db_session: AsyncSession, task: Task) -> list[str]:
    return [view.name for view in await list_task_nodes(db_session, task)]


async def _add(
    db_session: AsyncSession,
    task: Task,
    *,
    after: TaskNode | None,
    draft: CustomNodeDraft = _PROMPT,
) -> TaskNode:
    return await add_custom_task_node(
        db_session,
        task=task,
        after_task_node_id=after.id if after is not None else None,
        draft=draft,
    )


async def _add_history(db_session: AsyncSession, task: Task, task_node: TaskNode) -> None:
    db_session.add(
        NodeLog(
            task_id=task.id,
            node_id=task_node.node_id,
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
        ),
    )
    await db_session.commit()


class TestAddCustomNode:
    """Раздел 13.1: свой промт вставляется в снимок задачи со сдвигом последующих нод."""

    @pytest.mark.parametrize(
        ("after", "expected"),
        [
            (None, ["Уточнения", "node-0", "node-1"]),
            (0, ["node-0", "Уточнения", "node-1"]),
            (1, ["node-0", "node-1", "Уточнения"]),
        ],
    )
    async def test_inserted_at_position(
        self,
        db_session: AsyncSession,
        after: int | None,
        expected: list[str],
    ) -> None:
        task, task_nodes = await _new_task(db_session, 2)

        await _add(db_session, task, after=task_nodes[after] if after is not None else None)

        views = await list_task_nodes(db_session, task)
        assert [view.name for view in views] == expected
        assert [view.order_index for view in views] == [0, 1, 2]
        assert [view.is_custom for view in views] == [name == "Уточнения" for name in expected]

    async def test_custom_node_owned_by_task_with_default_limits(
        self,
        db_session: AsyncSession,
    ) -> None:
        task, task_nodes = await _new_task(db_session, 1)

        task_node = await _add(db_session, task, after=task_nodes[0])

        node = await db_session.get(Node, task_node.node_id)
        assert node is not None
        assert (node.task_id, node.pipeline_id, node.is_library_item) == (task.id, None, False)
        assert (node.timeout_seconds, node.max_retries) == (600, 3)

    @pytest.mark.parametrize(
        ("status", "after", "allowed"),
        [
            (TaskStatus.FAILED, 0, False),
            (TaskStatus.FAILED, None, False),
            (TaskStatus.FAILED, 1, True),
            (TaskStatus.IN_PROGRESS, 2, False),
            (TaskStatus.PAUSED, 2, False),
            (TaskStatus.DONE, 2, False),
        ],
    )
    async def test_position_rule_after_start(
        self,
        db_session: AsyncSession,
        status: TaskStatus,
        after: int | None,
        allowed: bool,
    ) -> None:
        task, task_nodes = await _make_task_with_nodes(
            db_session,
            status=status,
            last_failed_order_index=1 if status is TaskStatus.FAILED else None,
        )
        await db_session.commit()
        anchor = task_nodes[after] if after is not None else None

        if allowed:
            await _add(db_session, task, after=anchor)
            assert (await _names(db_session, task))[2] == "Уточнения"
        else:
            with pytest.raises(ConflictError):
                await _add(db_session, task, after=anchor)
            assert await _names(db_session, task) == ["node-0", "node-1", "node-2"]

    @pytest.mark.parametrize(
        "draft",
        [
            CustomNodeDraft(name="Скрипт", node_type=NodeType.SCRIPT, prompt_template="x"),
            CustomNodeDraft(name="План", node_type=NodeType.PLAN_PROMPT, prompt_template="x"),
            CustomNodeDraft(name=" ", node_type=NodeType.PLAIN_PROMPT, prompt_template="x"),
            CustomNodeDraft(name="Пусто", node_type=NodeType.PLAIN_PROMPT, prompt_template=" "),
            CustomNodeDraft(name="Команда", node_type=NodeType.SLASH_COMMAND, prompt_template="/x"),
            CustomNodeDraft(
                name="Скрипт раньше",
                node_type=NodeType.PLAIN_PROMPT,
                prompt_template="{{node.script_output}}",
            ),
        ],
        ids=["script", "plan", "no-name", "blank", "command-in-prompt-field", "unknown-source"],
    )
    async def test_invalid_draft_rejected(
        self,
        db_session: AsyncSession,
        draft: CustomNodeDraft,
    ) -> None:
        task, task_nodes = await _new_task(db_session, 1)
        await db_session.commit()

        with pytest.raises(ValidationError):
            await _add(db_session, task, after=task_nodes[0], draft=draft)

        assert await _names(db_session, task) == ["node-0"]

    async def test_slash_command_stored_literally(self, db_session: AsyncSession) -> None:
        task, _ = await _new_task(db_session, 1)
        draft = CustomNodeDraft(
            name="Ревью",
            node_type=NodeType.SLASH_COMMAND,
            prompt_template="лишнее",
            command_invocation="/review {{task.code}}",
        )

        await _add(db_session, task, after=None, draft=draft)

        view = (await list_task_nodes(db_session, task))[0]
        assert (view.command_invocation, view.prompt_template) == ("/review {{task.code}}", None)

    async def test_previous_custom_node_is_llm_source(self, db_session: AsyncSession) -> None:
        task, task_nodes = await _new_task(db_session, 1)
        first = await _add(db_session, task, after=task_nodes[0])
        follow_up = CustomNodeDraft(
            name="Ответы",
            node_type=NodeType.PLAIN_PROMPT,
            prompt_template="Учти: {{node.llm_output}}",
        )

        await _add(db_session, task, after=first, draft=follow_up)

        assert await _names(db_session, task) == ["node-0", "Уточнения", "Ответы"]


class TestEditDeleteCustomNode:
    """Раздел 3.2, 13.1: правка и удаление — только своей ноды и по правилу редактируемости."""

    async def test_edit_changes_text_and_type(self, db_session: AsyncSession) -> None:
        task, _ = await _new_task(db_session, 1)
        task_node = await _add(db_session, task, after=None)
        draft = CustomNodeDraft(
            name="Ревью",
            node_type=NodeType.SLASH_COMMAND,
            command_invocation="/review",
        )

        await update_custom_task_node(db_session, task=task, task_node_id=task_node.id, draft=draft)

        view = (await list_task_nodes(db_session, task))[0]
        assert (view.name, view.node_type, view.command_invocation) == (
            "Ревью",
            NodeType.SLASH_COMMAND,
            "/review",
        )
        assert view.prompt_template is None

    async def test_delete_without_history(self, db_session: AsyncSession) -> None:
        task, task_nodes = await _new_task(db_session, 2)
        task_node = await _add(db_session, task, after=task_nodes[0])

        await delete_custom_task_node(db_session, task=task, task_node_id=task_node.id)

        assert await _names(db_session, task) == ["node-0", "node-1"]
        assert await db_session.get(Node, task_node.node_id) is None

    async def test_delete_with_history_conflicts(self, db_session: AsyncSession) -> None:
        task, _ = await _new_task(db_session, 1)
        task_node = await _add(db_session, task, after=None)
        await _add_history(db_session, task, task_node)

        with pytest.raises(ConflictError):
            await delete_custom_task_node(db_session, task=task, task_node_id=task_node.id)

        assert await _names(db_session, task) == ["Уточнения", "node-0"]

    @pytest.mark.parametrize("operation", ["update", "delete"])
    async def test_pipeline_node_not_editable(
        self,
        db_session: AsyncSession,
        operation: str,
    ) -> None:
        task, task_nodes = await _new_task(db_session, 1)

        with pytest.raises(ConflictError):
            if operation == "update":
                await update_custom_task_node(
                    db_session,
                    task=task,
                    task_node_id=task_nodes[0].id,
                    draft=_PROMPT,
                )
            else:
                await delete_custom_task_node(db_session, task=task, task_node_id=task_nodes[0].id)

    async def test_locked_in_failed_before_failure_point(self, db_session: AsyncSession) -> None:
        task, task_nodes = await _new_task(db_session, 2)
        task_node = await _add(db_session, task, after=task_nodes[0])
        task.status = TaskStatus.FAILED
        task.last_failed_order_index = 2
        await db_session.commit()

        with pytest.raises(ConflictError):
            await delete_custom_task_node(db_session, task=task, task_node_id=task_node.id)

    async def test_delete_breaking_template_rolls_back(self, db_session: AsyncSession) -> None:
        task, _ = await _new_task(db_session, 0)
        first = await _add(db_session, task, after=None)
        await _add(
            db_session,
            task,
            after=first,
            draft=CustomNodeDraft(
                name="Ответы",
                node_type=NodeType.PLAIN_PROMPT,
                prompt_template="{{node.llm_output}}",
            ),
        )

        with pytest.raises(ValidationError):
            await delete_custom_task_node(db_session, task=task, task_node_id=first.id)

        assert await _names(db_session, task) == ["Уточнения", "Ответы"]


class TestCustomNodesLifecycle:
    """Раздел 13.1: смена пайплайна убирает свои ноды, дублирование их копирует."""

    async def test_rebind_removes_unused_custom_nodes(self, db_session: AsyncSession) -> None:
        task, _ = await _new_task(db_session, 1)
        unused = await _add(db_session, task, after=None)
        executed = await _add(db_session, task, after=unused)
        await _add_history(db_session, task, executed)
        assert task.pipeline_id is not None

        await bind_pipeline_to_task(
            db_session,
            task=task,
            pipeline_id=task.pipeline_id,
            disabled_node_ids=None,
        )

        assert await _names(db_session, task) == ["node-0"]
        assert await db_session.get(Node, unused.node_id) is None
        assert await db_session.get(Node, executed.node_id) is not None

    async def test_reset_keeps_custom_nodes(self, db_session: AsyncSession) -> None:
        task, _ = await _new_task(db_session, 1)
        await _add(db_session, task, after=None)
        task.status = TaskStatus.FAILED
        task.last_failed_order_index = 0
        await db_session.commit()

        await reset_task_to_new(db_session, task_id=task.id)

        assert await _names(db_session, task) == ["Уточнения", "node-0"]

    async def test_duplicate_copies_custom_nodes(self, db_session: AsyncSession) -> None:
        source, task_nodes = await _new_task(db_session, 1)
        custom = await _add(db_session, source, after=task_nodes[0])
        await set_task_node_pause_after(
            db_session,
            task=source,
            task_node_id=custom.id,
            pause_after=True,
        )
        source.status = TaskStatus.DONE
        await db_session.commit()

        copy = await duplicate_task(
            db_session,
            source=source,
            draft=TaskDraft(code=f"RR-{uuid.uuid4().hex[:5]}", title="копия", description="d"),
            created_by=source.created_by,
        )

        views = await list_task_nodes(db_session, copy)
        assert [(view.name, view.is_custom, view.pause_after) for view in views] == [
            ("node-0", False, False),
            ("Уточнения", True, True),
        ]
        copied_node = await db_session.get(Node, views[1].node_id)
        assert copied_node is not None
        assert (copied_node.task_id, copied_node.prompt_template) == (copy.id, "Задай вопросы")
        source_ids = await db_session.scalars(
            sa.select(TaskNode.node_id).where(TaskNode.task_id == source.id),
        )
        assert views[1].node_id not in set(source_ids)
