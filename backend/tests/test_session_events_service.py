"""Раздел 15.2: событие «новая сессия» не дублируется при повторном старте воркера."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from db.models.enums import NodeLogStatus, NodeLogTriggerType, TaskSessionEventKind
from db.models.logs import NodeLog
from db.queries.session_events import list_session_events
from services.session_events import add_session_event, record_new_session
from tests.factories import make_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _kinds(db_session: AsyncSession, task_id: uuid.UUID) -> list[str]:  # noqa: ANN001
    return [event.kind.value for event in await list_session_events(db_session, task_id)]


class TestRecordNewSession:
    async def test_repeated_start_without_turns_adds_one_event(
        self, db_session: AsyncSession
    ) -> None:
        task = await make_task(db_session)

        await record_new_session(db_session, task_id=task.id)
        await record_new_session(db_session, task_id=task.id)

        assert await _kinds(db_session, task.id) == ["session_started"]

    async def test_new_session_after_a_turn_is_noted(self, db_session: AsyncSession) -> None:
        task = await make_task(db_session)
        await record_new_session(db_session, task_id=task.id)
        db_session.add(
            NodeLog(
                task_id=task.id,
                node_id=None,
                trigger_type=NodeLogTriggerType.FREEFORM_MANUAL,
                status=NodeLogStatus.SUCCESS,
                started_at=datetime.now(UTC) + timedelta(seconds=1),
            ),
        )
        await db_session.commit()

        await record_new_session(db_session, task_id=task.id)

        assert await _kinds(db_session, task.id) == ["session_started", "session_started"]

    @pytest.mark.parametrize("previous", [TaskSessionEventKind.CONTEXT_CLEARED])
    async def test_session_after_context_clear_is_noted(
        self,
        db_session: AsyncSession,
        previous: TaskSessionEventKind,
    ) -> None:
        task = await make_task(db_session)
        add_session_event(db_session, task_id=task.id, kind=previous)
        await db_session.commit()

        await record_new_session(db_session, task_id=task.id)

        assert await _kinds(db_session, task.id) == [previous.value, "session_started"]
