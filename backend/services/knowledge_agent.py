"""Встроенные MCP-инструменты базы знаний для сессии задачи."""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy as sa
from claude_agent_sdk import create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.knowledge import KnowledgeEntry
from db.models.tasks import Task
from db.models.users import User
from db.session import async_session_factory
from services.errors import AppError, NotFoundError
from services.knowledge_access import KnowledgeAccess, knowledge_access_for_role
from services.knowledge_files import change_deleted, entry_content, move_entry, write_entry
from services.knowledge_sections import (
    SESSION_KNOWLEDGE_ACCESS,
    KnowledgeSectionSnapshot,
    section_snapshot,
)
from services.knowledge_views import publish_section


async def build_knowledge_tools(
    db: AsyncSession, *, task: Task, sections: list[KnowledgeSectionSnapshot] | None = None
) -> McpSdkServerConfig:
    user = await db.get(User, task.created_by)
    if user is None:
        raise NotFoundError("Автор задачи не найден")
    sections = sections if sections is not None else await section_snapshot(db, user=user)
    permissions = {
        section.id: knowledge_access_for_role(
            user.role, user_access=KnowledgeAccess(read=section.user_read, write=section.user_write)
        )
        for section in sections
    }
    visible = {str(section.id): section for section in sections}

    @tool(
        "list",
        "Read corporate maps at /workspace/knowledge/<section_id>/. Write via MCP.",
        {},
    )
    async def list_knowledge(_args: dict[str, Any]) -> dict[str, Any]:
        async with async_session_factory() as session:
            entries = list(
                await session.scalars(
                    sa.select(KnowledgeEntry)
                    .where(
                        KnowledgeEntry.section_id.in_([section.id for section in sections]),
                        KnowledgeEntry.deleted_at.is_(None),
                    )
                    .order_by(KnowledgeEntry.path)
                )
            )
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "sections": [
                                {"id": str(section.id), "name": section.name}
                                for section in sections
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
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }

    @tool("read", "Read a shared knowledge file and its version before editing.", {"entry_id": str})
    async def read_knowledge(args: dict[str, Any]) -> dict[str, Any]:
        try:
            async with async_session_factory() as session:
                entry = await session.get(KnowledgeEntry, uuid.UUID(args["entry_id"]))
                if (
                    entry is None
                    or str(entry.section_id) not in visible
                    or entry.deleted_at is not None
                ):
                    raise NotFoundError("Файл не найден")
                text = (await entry_content(session, entry=entry)).decode()
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"version": entry.version, "content": text}, ensure_ascii=False
                            ),
                        }
                    ]
                }
        except (AppError, ValueError) as exc:
            return {"is_error": True, "content": [{"type": "text", "text": str(exc)}]}

    @tool(
        "write",
        "Write shared knowledge. Use expected_version=0 for new files. Read and merge on conflict.",
        {
            "type": "object",
            "properties": {
                "section_id": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
                "expected_version": {"type": "integer", "minimum": 0},
                "is_directory": {"type": "boolean", "default": False},
            },
            "required": ["section_id", "path", "content", "expected_version"],
        },
    )
    async def write_knowledge(args: dict[str, Any]) -> dict[str, Any]:
        token = SESSION_KNOWLEDGE_ACCESS.set(permissions)
        try:
            async with async_session_factory() as session:
                entry = await write_entry(
                    db=session,
                    user=user,
                    section_id=uuid.UUID(args["section_id"]),
                    path=args["path"],
                    content=args["content"].encode(),
                    expected_version=args["expected_version"],
                    task_id=task.id,
                    is_directory=args.get("is_directory", False),
                )
                await session.commit()
                await publish_section(session, section_id=entry.section_id)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"id": str(entry.id), "version": entry.version}),
                        }
                    ]
                }
        except (AppError, ValueError) as exc:
            return {"is_error": True, "content": [{"type": "text", "text": str(exc)}]}

        finally:
            SESSION_KNOWLEDGE_ACCESS.reset(token)

    @tool(
        "move",
        "Rename or move knowledge files and folders with version checking.",
        {"entry_id": str, "section_id": str, "path": str, "expected_version": int},
    )
    async def move_knowledge(args: dict[str, Any]) -> dict[str, Any]:
        token = SESSION_KNOWLEDGE_ACCESS.set(permissions)
        try:
            async with async_session_factory() as session:
                original = await session.get(KnowledgeEntry, uuid.UUID(args["entry_id"]))
                if original is None:
                    raise NotFoundError("Файл не найден")
                source = original.section_id
                entry = await move_entry(
                    db=session,
                    user=user,
                    entry_id=original.id,
                    section_id=uuid.UUID(args["section_id"]),
                    path=args["path"],
                    expected_version=args["expected_version"],
                    task_id=task.id,
                )
                await session.commit()
                await publish_section(session, section_id=source)
                if source != entry.section_id:
                    await publish_section(session, section_id=entry.section_id)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"id": str(entry.id), "version": entry.version}),
                        }
                    ]
                }
        except (AppError, ValueError) as exc:
            return {"is_error": True, "content": [{"type": "text", "text": str(exc)}]}
        finally:
            SESSION_KNOWLEDGE_ACCESS.reset(token)

    @tool(
        "trash",
        "Move a knowledge file/folder to trash or restore it. Requires write permission.",
        {"entry_id": str, "expected_version": int, "deleted": bool},
    )
    async def trash_knowledge(args: dict[str, Any]) -> dict[str, Any]:
        token = SESSION_KNOWLEDGE_ACCESS.set(permissions)
        try:
            async with async_session_factory() as session:
                entry = await change_deleted(
                    db=session,
                    user=user,
                    entry_id=uuid.UUID(args["entry_id"]),
                    expected_version=args["expected_version"],
                    deleted=args["deleted"],
                    task_id=task.id,
                )
                await session.commit()
                await publish_section(session, section_id=entry.section_id)
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"id": str(entry.id), "version": entry.version}),
                        }
                    ]
                }
        except (AppError, ValueError) as exc:
            return {"is_error": True, "content": [{"type": "text", "text": str(exc)}]}
        finally:
            SESSION_KNOWLEDGE_ACCESS.reset(token)

    return create_sdk_mcp_server(
        name="tracker-knowledge",
        tools=[list_knowledge, read_knowledge, write_knowledge, move_knowledge, trash_knowledge],
    )
