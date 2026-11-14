import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import create_sdk_mcp_server
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import TaskStatus
from db.models.knowledge import KnowledgeSection
from db.models.tasks import Task
from db.models.users import User
from services import knowledge_agent
from tests.test_plan_mode import _non_closing_session_factory


class TestKnowledgeAgent:
    async def test_session_rights_are_frozen(
        self,
        db_session: AsyncSession,
        current_user: User,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("TRACKER_KNOWLEDGE_ROOT", str(tmp_path))
        section = KnowledgeSection(
            name="Shared", user_read=True, user_write=True, created_by=current_user.id
        )
        task = Task(
            code="KNOW-" + uuid.uuid4().hex[:5],
            title="Knowledge",
            description="d",
            created_by=current_user.id,
            status=TaskStatus.IN_PROGRESS,
        )
        db_session.add_all([section, task])
        await db_session.flush()
        tools: dict[str, Any] = {}
        real_create = create_sdk_mcp_server

        def capture(**kwargs: Any) -> Any:
            tools.update({tool.name: tool for tool in kwargs["tools"]})
            return real_create(**kwargs)

        monkeypatch.setattr(knowledge_agent, "create_sdk_mcp_server", capture)
        monkeypatch.setattr(
            knowledge_agent, "async_session_factory", _non_closing_session_factory(db_session)
        )
        await knowledge_agent.build_knowledge_tools(db_session, task=task)
        section.user_write = False
        await db_session.commit()
        result = await tools["write"].handler(
            {
                "section_id": str(section.id),
                "path": "Map.md",
                "content": "map",
                "expected_version": 0,
            }
        )
        assert not result.get("is_error"), result
        entry_id = json.loads(result["content"][0]["text"])["id"]
        result = await tools["move"].handler(
            {
                "entry_id": entry_id,
                "section_id": str(section.id),
                "path": "Moved.md",
                "expected_version": 1,
            }
        )
        assert not result.get("is_error"), result
        for version, deleted in [(2, True), (3, False)]:
            result = await tools["trash"].handler(
                {"entry_id": entry_id, "expected_version": version, "deleted": deleted}
            )
            assert not result.get("is_error"), result
        await knowledge_agent.build_knowledge_tools(db_session, task=task)
        result = await tools["write"].handler(
            {
                "section_id": str(section.id),
                "path": "Other.md",
                "content": "map",
                "expected_version": 0,
            }
        )
        assert result.get("is_error"), result
