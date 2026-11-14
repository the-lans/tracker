"""
Адаптер MCP: фиксированные права сессии и вызовы прикладных команд.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.knowledge import KnowledgeEntry
from db.models.tasks import Task
from db.models.users import User
from db.queries import knowledge as queries
from db.session import async_session_factory
from services import knowledge_commands as commands
from services.errors import AppError, NotFoundError
from services.knowledge_access import knowledge_access_for_role
from services.knowledge_files import entry_content
from services.knowledge_objects import KnowledgeAccess, KnowledgeSectionSnapshot
from services.knowledge_reader import readable_entry
from services.knowledge_sections import SESSION_KNOWLEDGE_ACCESS, section_snapshot

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ToolArguments = dict[str, Any]
ToolMethod = Callable[[AsyncSession, ToolArguments], Awaitable[object]]


class KnowledgeAgentTools:
    def __init__(
        self,
        *,
        user: User,
        task_id: uuid.UUID,
        sections: list[KnowledgeSectionSnapshot],
        session_factory: SessionFactory,
    ) -> None:
        self.user = user
        self.task_id = task_id
        self.sections = sections
        self.session_factory = session_factory
        self.permissions = {
            section.id: knowledge_access_for_role(
                user.role,
                user_access=KnowledgeAccess(read=section.user_read, write=section.user_write),
            )
            for section in sections
        }

    async def execute(self, method: ToolMethod, args: ToolArguments) -> dict[str, Any]:
        token = SESSION_KNOWLEDGE_ACCESS.set(self.permissions)
        try:
            async with self.session_factory() as db:
                payload = await method(db, args)
            return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
        except (AppError, ValueError) as exc:
            return {"is_error": True, "content": [{"type": "text", "text": str(exc)}]}
        finally:
            SESSION_KNOWLEDGE_ACCESS.reset(token)

    async def list(self, db: AsyncSession, _args: ToolArguments) -> object:
        entries = await queries.entries(db, section_ids=list(self.permissions), live_only=True)
        return {
            "sections": [
                {"id": str(section.id), "name": section.name} for section in self.sections
            ],
            "files": [
                {
                    "id": str(entry.id),
                    "section_id": str(entry.section_id),
                    "path": entry.path,
                    "version": entry.version,
                }
                for entry in entries
            ],
        }

    async def read(self, db: AsyncSession, args: ToolArguments) -> object:
        entry = await readable_entry(db, user=self.user, entry_id=uuid.UUID(args["entry_id"]))
        if entry.deleted_at is not None:
            raise NotFoundError("Файл не найден")
        return {
            "version": entry.version,
            "content": (await entry_content(db, entry=entry)).decode(),
        }

    async def _result(self, db: AsyncSession, entry: KnowledgeEntry) -> object:
        section = await queries.section(db, entry.section_id)
        return {
            "id": str(entry.id),
            "version": entry.version,
            "publication_pending": section.publication_pending if section else False,
        }

    async def write(self, db: AsyncSession, args: ToolArguments) -> object:
        entry = await commands.save(
            db=db,
            user=self.user,
            section_id=uuid.UUID(args["section_id"]),
            path=args["path"],
            content=args["content"].encode(),
            expected_version=args["expected_version"],
            task_id=self.task_id,
            is_directory=args.get("is_directory", False),
        )
        return await self._result(db, entry)

    async def move(self, db: AsyncSession, args: ToolArguments) -> object:
        entry = await commands.move(
            db=db,
            user=self.user,
            entry_id=uuid.UUID(args["entry_id"]),
            section_id=uuid.UUID(args["section_id"]),
            path=args["path"],
            expected_version=args["expected_version"],
            task_id=self.task_id,
        )
        return await self._result(db, entry)

    async def trash(self, db: AsyncSession, args: ToolArguments) -> object:
        entry = await commands.set_deleted(
            db=db,
            user=self.user,
            entry_id=uuid.UUID(args["entry_id"]),
            expected_version=args["expected_version"],
            deleted=args["deleted"],
            task_id=self.task_id,
        )
        return await self._result(db, entry)

    def handler(self, method: ToolMethod) -> Callable[[ToolArguments], Awaitable[dict[str, Any]]]:
        async def invoke(args: ToolArguments) -> dict[str, Any]:
            return await self.execute(method, args)

        return invoke


_WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "section_id": {"type": "string"},
        "path": {"type": "string"},
        "content": {"type": "string"},
        "expected_version": {"type": "integer", "minimum": 0},
        "is_directory": {"type": "boolean", "default": False},
    },
    "required": ["section_id", "path", "content", "expected_version"],
}


async def build_knowledge_tools(
    db: AsyncSession,
    *,
    task: Task,
    sections: list[KnowledgeSectionSnapshot] | None = None,
    session_factory: SessionFactory | None = None,
) -> McpSdkServerConfig:
    user = await queries.owner(db, task.created_by)
    if user is None:
        raise NotFoundError("Автор задачи не найден")
    snapshot = sections if sections is not None else await section_snapshot(db, user=user)
    agent = KnowledgeAgentTools(
        user=user,
        task_id=task.id,
        sections=snapshot,
        session_factory=session_factory or async_session_factory,
    )
    definitions: list[tuple[str, str, dict[str, Any], ToolMethod]] = [
        (
            "list",
            "Read corporate maps at /workspace/knowledge/<section_id>/. Write via MCP.",
            {},
            agent.list,
        ),
        (
            "read",
            "Read a shared knowledge file and its version before editing.",
            {"entry_id": str},
            agent.read,
        ),
        (
            "write",
            "Write knowledge with expected_version=0 for new files. Read and merge on conflict.",
            _WRITE_SCHEMA,
            agent.write,
        ),
        (
            "move",
            "Rename or move knowledge files and folders with version checking.",
            {"entry_id": str, "section_id": str, "path": str, "expected_version": int},
            agent.move,
        ),
        (
            "trash",
            "Move a knowledge file/folder to trash or restore it. Requires write permission.",
            {"entry_id": str, "expected_version": int, "deleted": bool},
            agent.trash,
        ),
    ]
    return create_sdk_mcp_server(
        name="tracker-knowledge",
        tools=[
            tool(name, description, schema)(agent.handler(method))
            for name, description, schema, method in definitions
        ],
    )
