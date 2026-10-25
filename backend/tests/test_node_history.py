"""
Тесты `services/node_history.py`: источники `{{node.*}}` (раздел 5 ТЗ) —
успешные ноды пайплайна текущего прогона и реплики текущей сессии.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import NodeLogStatus, NodeLogTriggerType, NodeType
from db.models.logs import NodeLog
from db.models.pipelines import Node
from services.node_history import load_node_context_history
from tests.factories import make_pipeline, make_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

_START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


async def _task_with_node(db_session: AsyncSession, **fields: Any) -> tuple[Task, uuid.UUID]:
    task = await make_task(db_session, **fields)
    pipeline = await make_pipeline(db_session, created_by=task.created_by)
    node = Node(
        created_by=task.created_by,
        pipeline_id=pipeline.id,
        order_index=0,
        name="шаг",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="шаг",
        timeout_seconds=60,
        is_library_item=False,
    )
    db_session.add(node)
    await db_session.flush()
    return task, node.id


def _log(
    task: Task,
    *,
    node_id: uuid.UUID | None,
    minute: int,
    text: str,
    trigger_type: NodeLogTriggerType = NodeLogTriggerType.PIPELINE,
    status: NodeLogStatus = NodeLogStatus.SUCCESS,
) -> NodeLog:
    return NodeLog(
        task_id=task.id,
        node_id=node_id,
        trigger_type=trigger_type,
        status=status,
        llm_output_text=text,
        started_at=_START + timedelta(minutes=minute),
    )


class TestLoadNodeContextHistory:
    @pytest.mark.parametrize(
        ("trigger_type", "status", "with_node"),
        [
            # Повтор после таймаута: обрывок ответа упавшей попытки.
            (NodeLogTriggerType.PIPELINE, NodeLogStatus.FAILED, True),
            (NodeLogTriggerType.PIPELINE, NodeLogStatus.STOPPED, True),
            # Агент разрешил конфликт ребейза между нодами.
            (NodeLogTriggerType.PIPELINE, NodeLogStatus.SUCCESS, False),
            (NodeLogTriggerType.LIBRARY_MANUAL, NodeLogStatus.SUCCESS, True),
            (NodeLogTriggerType.FREEFORM_MANUAL, NodeLogStatus.SUCCESS, False),
            (NodeLogTriggerType.PARENT_SUMMARY, NodeLogStatus.SUCCESS, False),
        ],
    )
    async def test_previous_pipeline_node_wins(
        self,
        db_session: AsyncSession,
        trigger_type: NodeLogTriggerType,
        status: NodeLogStatus,
        with_node: bool,
    ) -> None:
        task, node_id = await _task_with_node(db_session)
        db_session.add_all(
            [
                _log(task, node_id=node_id, minute=0, text="ответ ноды A"),
                _log(
                    task,
                    node_id=node_id if with_node else None,
                    minute=1,
                    text="посторонний ответ",
                    trigger_type=trigger_type,
                    status=status,
                ),
            ],
        )
        await db_session.flush()

        history = await load_node_context_history(db_session, task)

        assert [entry.llm_output_text for entry in history.pipeline_runs] == ["ответ ноды A"]
        # Реплика всё равно прозвучала в сессии.
        assert history.session_replies == ["ответ ноды A", "посторонний ответ"]

    async def test_previous_run_excluded(self, db_session: AsyncSession) -> None:
        """«Вернуть в новые»: прошлый прогон не даёт `{{node.*}}`, сессия та же."""
        task, node_id = await _task_with_node(db_session, reset_at=_START + timedelta(minutes=5))
        db_session.add_all(
            [
                _log(task, node_id=node_id, minute=0, text="прошлый прогон"),
                _log(task, node_id=node_id, minute=6, text="новый прогон"),
            ],
        )
        await db_session.flush()

        history = await load_node_context_history(db_session, task)

        assert [entry.llm_output_text for entry in history.pipeline_runs] == ["новый прогон"]
        assert history.session_replies == ["прошлый прогон", "новый прогон"]

    async def test_previous_session_excluded(self, db_session: AsyncSession) -> None:
        task, node_id = await _task_with_node(
            db_session,
            context_cleared_at=_START + timedelta(minutes=5),
        )
        db_session.add_all(
            [
                _log(task, node_id=node_id, minute=0, text="до очистки"),
                _log(task, node_id=node_id, minute=6, text="после очистки"),
            ],
        )
        await db_session.flush()

        history = await load_node_context_history(db_session, task)

        assert history.session_replies == ["после очистки"]
        assert len(history.pipeline_runs) == 2
