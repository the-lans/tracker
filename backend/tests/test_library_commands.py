"""
Команды библиотеки: аргументы, изоляция владельцев, снимки и исполнение очереди.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from clients.claude_agent import ClaudeCodeSession
from db.models.enums import EnvVariableScope, NodeLogStatus, NodeType, ScriptLanguage, TaskStatus
from db.models.env_vars import EnvVariable
from db.models.logs import NodeLog
from db.models.pipelines import Node
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.tasks import Task
from db.models.users import User
from services.command_arguments import normalize_slash_name, parse_invocation, prepare_arguments
from services.crypto import decrypt, encrypt
from services.errors import ConflictError, ValidationError
from services.integrity import count_library_prompt_usage
from services.library_commands import (
    CommandSnapshot,
    enqueue_command,
    load_snapshot,
    render_command,
)
from services.manual_queue import process_manual_queue_once
from services.template_context import SECRET_MASK
from tests.factories import make_llm_account, make_task, make_user
from tests.fakes import FakeClaudeAgentClient, make_result_message


@pytest.fixture
async def command_task(db_session: AsyncSession, current_user: User) -> Task:
    account = await make_llm_account(db_session, owner_id=current_user.id)
    return await make_task(
        db_session,
        created_by=current_user.id,
        status=TaskStatus.IN_PROGRESS,
        llm_account_id=account.id,
    )


@pytest.fixture
async def command_node(db_session: AsyncSession, current_user: User) -> Node:
    node = Node(
        created_by=current_user.id,
        name="Ревью",
        description="Проверить изменения",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template="Проверь $1. $ARGUMENTS",
        slash_name="review",
        is_library_item=True,
    )
    db_session.add(node)
    await db_session.flush()
    return node


class TestArguments:
    @pytest.mark.parametrize(
        ("template", "raw", "expected"),
        [
            ("$ARGUMENTS", 'service "two words"', 'service "two words"'),
            ("$1/$2/$ARGUMENTS[2]", 'service "two words"', "service/two words/two words"),
            ("$01/$ARGUMENTS[1]", "one", "one/one"),
            ("$0/$ARGUMENTS[0]", "one", "$0/$ARGUMENTS[0]\n\nARGUMENTS: one"),
            ("$2", "one", "$2\n\nARGUMENTS: one"),
            ("hello", "one", "hello\n\nARGUMENTS: one"),
            (r"\$1", "one", "$1\n\nARGUMENTS: one"),
            (r"\\$1", "one", r"\\one"),
            ("$1", '"$ARGUMENTS {{task.title}}"', "$ARGUMENTS {{task.title}}"),
            ("$1", '""', ""),
            ("$ARGUMENTS", "", ""),
        ],
    )
    def test_substitution(self, template: str, raw: str, expected: str) -> None:
        prepared = prepare_arguments(template, parse_invocation("/review " + raw))
        assert prepared.expand(prepared.text) == expected

    @pytest.mark.parametrize("invocation", ["review x", "/review 'broken", "/review \x00", "/../x"])
    def test_invalid_input(self, invocation: str) -> None:
        with pytest.raises(ValidationError):
            parse_invocation(invocation)

    @pytest.mark.parametrize(
        ("value", "expected"), [(None, None), ("", None), (" /ReView ", "review")]
    )
    def test_normalization(self, value: str | None, expected: str | None) -> None:
        assert normalize_slash_name(value) == expected


class TestCommandAPI:
    async def test_create_unique_alias(self, authed_client: AsyncClient) -> None:
        body = dict(
            name="Review",
            description="Review changes",
            node_type="plain_prompt",
            prompt_template="Check $1",
            slash_name="/ReView",
            argument_hint="[service]",
        )
        first = await authed_client.post("/nodes", json=body)
        assert first.status_code == 201 and first.json()["slash_name"] == "review"
        duplicate = await authed_client.post("/nodes", json=body)
        assert duplicate.status_code == 409

    async def test_duplicate_alias_full_form(self, authed_client: AsyncClient) -> None:
        body = dict(
            name="One",
            description="test",
            node_type="plain_prompt",
            prompt_template="test",
            slash_name="one",
        )
        assert (await authed_client.post("/nodes", json=body)).status_code == 201
        second = await authed_client.post("/nodes", json={**body, "slash_name": "two"})
        response = await authed_client.patch(
            f"/nodes/{second.json()['id']}",
            json={
                "slash_name": "one",
                "timeout_seconds": 600,
            },
        )
        assert response.status_code == 409

    @pytest.mark.parametrize(
        "invocation", ["/plugin:review", "/compact Focus on the user's changes"]
    )
    async def test_native_command_fallback(
        self,
        authed_client: AsyncClient,
        command_task: Task,
        invocation: str,
    ) -> None:
        response = await authed_client.post(
            f"/tasks/{command_task.id}/commands/run",
            json={
                "invocation": invocation,
                "client_request_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 404
        preview = await authed_client.post(
            f"/tasks/{command_task.id}/commands/preview",
            json={
                "invocation": invocation,
            },
        )
        assert preview.status_code == 404

    async def test_archive_reserves_name(
        self, authed_client: AsyncClient, command_node: Node
    ) -> None:
        archived = await authed_client.patch(
            f"/nodes/{command_node.id}", json={"is_archived": True}
        )
        assert archived.status_code == 200
        assert archived.json()["revision"] == 2
        duplicate = await authed_client.post(
            "/nodes",
            json={
                "name": "Other",
                "description": "x",
                "node_type": "plain_prompt",
                "prompt_template": "test",
                "slash_name": "review",
            },
        )
        assert duplicate.status_code == 409

    async def test_list_run_preview(
        self,
        redis_client: Redis,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        command_node: Node,
        command_task: Task,
    ) -> None:
        base = f"/tasks/{command_task.id}/commands"
        rows = await authed_client.get(base)
        assert rows.status_code == 200 and rows.json()[0]["slash_name"] == "review"
        preview = await authed_client.post(
            base + "/preview", json={"invocation": "/review service"}
        )
        assert preview.json()["rendered_text"] == "Проверь service. service"
        body = {"invocation": "/review service", "client_request_id": str(uuid.uuid4())}
        first = await authed_client.post(base + "/run", json=body)
        second = await authed_client.post(base + "/run", json=body)
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["command_revision"] == 1
        assert dict(await count_library_prompt_usage(db_session))[command_node.id] == 1
        assert "snapshot" not in first.text and "service" not in first.text
        assert (
            await db_session.scalar(sa.select(sa.func.count()).select_from(TaskLibraryPrompt)) == 0
        )
        assert (
            await db_session.scalar(sa.select(sa.func.count()).select_from(TaskManualRequestQueue))
            == 1
        )
        conflict = await authed_client.post(
            base + "/run", json={**body, "invocation": "/review other"}
        )
        assert conflict.status_code == 409
        assert (await authed_client.delete(f"/nodes/{command_node.id}")).status_code == 409

    async def test_other_owner_hidden(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        command_task: Task,
    ) -> None:
        other = await make_user(db_session)
        db_session.add(
            Node(
                created_by=other.id,
                name="Other",
                slash_name="review",
                is_library_item=True,
                node_type=NodeType.PLAIN_PROMPT,
            )
        )
        await db_session.flush()
        base = f"/tasks/{command_task.id}/commands"
        assert (await authed_client.get(base)).json() == []
        response = await authed_client.post(
            base + "/run",
            json={
                "invocation": "/review",
                "client_request_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 404
        foreign = await make_task(db_session, created_by=other.id, status=TaskStatus.IN_PROGRESS)
        assert (await authed_client.get(f"/tasks/{foreign.id}/commands")).status_code == 404

    @pytest.mark.parametrize("slash_name", ["/bad name", "/../file", "/команда", "/1name"])
    async def test_invalid_name(self, authed_client: AsyncClient, slash_name: str) -> None:
        response = await authed_client.post(
            "/nodes",
            json={
                "name": "Review",
                "description": "x",
                "node_type": "plain_prompt",
                "prompt_template": "test",
                "slash_name": slash_name,
            },
        )
        assert response.status_code == 422


class TestCommandExecution:
    async def test_frozen_prompt(
        self,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        request = await enqueue_command(
            db_session,
            task=command_task,
            requested_by=command_task.created_by,
            invocation='/review "$ARGUMENTS {{task.title}}"',
            client_request_id=uuid.uuid4(),
        )
        assert (
            request.command_snapshot_encrypted
            and "Проверь" not in request.command_snapshot_encrypted
        )
        snapshot = load_snapshot(request)
        command_node.prompt_template = "CHANGED"
        command_node.is_archived = True
        command_node.slash_name = "renamed"
        command_node.revision = 2
        await db_session.commit()
        rendered = await render_command(
            db_session, task=command_task, request=request, snapshot=snapshot
        )
        assert (
            rendered
            and rendered.text == 'Проверь $ARGUMENTS {{task.title}}. "$ARGUMENTS {{task.title}}"'
        )
        fake = FakeClaudeAgentClient(messages_per_query=[[make_result_message()]])
        count = await process_manual_queue_once(
            db_session,
            task=command_task,
            claude_session=ClaudeCodeSession(fake),
            repos_path=tmp_path,
            redis_client=redis_client,
        )
        assert count == 1
        log = (
            await db_session.scalars(sa.select(NodeLog).where(NodeLog.task_id == command_task.id))
        ).one()
        assert log.status == NodeLogStatus.SUCCESS
        assert log.command_name == "review" and log.command_revision == 1
        assert log.rendered_prompt == rendered.display

    async def test_runtime_variables_are_masked(
        self,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
    ) -> None:
        command_node.prompt_template = "{{task.title}} {{env.TOKEN}} $1"
        variable = EnvVariable(
            key="TOKEN",
            value_encrypted=encrypt("OLD"),
            is_secret=True,
            scope=EnvVariableScope.GLOBAL,
        )
        db_session.add(variable)
        await db_session.commit()
        request = await enqueue_command(
            db_session,
            task=command_task,
            requested_by=command_task.created_by,
            invocation='/review "{{env.TOKEN}}"',
            client_request_id=uuid.uuid4(),
        )
        command_task.title = "UPDATED"
        variable.value_encrypted = encrypt("NEW_SECRET")
        await db_session.commit()
        snapshot = load_snapshot(request)
        rendered = await render_command(
            db_session, task=command_task, request=request, snapshot=snapshot
        )
        assert rendered is not None
        assert rendered.text == "UPDATED NEW_SECRET {{env.TOKEN}}"
        assert rendered.display == f"UPDATED {SECRET_MASK} {{{{env.TOKEN}}}}"
        assert "NEW_SECRET" not in snapshot.model_dump_json()

    @pytest.mark.parametrize(
        ("snapshot_guide", "expected"),
        [("https://wiki.example.com/g", "гайд https://wiki.example.com/g"), (None, "гайд ")],
        ids=["в-снимке", "снимок-до-поля"],
    )
    async def test_guide_url_from_snapshot(
        self,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
        snapshot_guide: str | None,
        expected: str,
    ) -> None:
        command_node.prompt_template = "гайд {{node.guide_url}}"
        command_node.guide_url = "https://wiki.example.com/g"
        await db_session.commit()
        request = await enqueue_command(
            db_session,
            task=command_task,
            requested_by=command_task.created_by,
            invocation="/review",
            client_request_id=uuid.uuid4(),
        )
        stored = load_snapshot(request).model_dump(exclude={"guide_url"})
        if snapshot_guide is not None:
            stored["guide_url"] = snapshot_guide
        snapshot = CommandSnapshot.model_validate(stored)

        rendered = await render_command(
            db_session, task=command_task, request=request, snapshot=snapshot
        )

        assert rendered is not None and rendered.text == expected

    @pytest.mark.parametrize(
        ("guide", "stored"),
        [("https://wiki.example.com/g", True), (None, False)],
        ids=["гайд-есть", "без-гайда"],
    )
    async def test_snapshot_omits_empty_guide(
        self,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
        guide: str | None,
        stored: bool,
    ) -> None:
        """Раздел 20.6: снимок без гайда читает и версия до появления поля."""
        command_node.guide_url = guide
        await db_session.commit()
        request = await enqueue_command(
            db_session,
            task=command_task,
            requested_by=command_task.created_by,
            invocation="/review",
            client_request_id=uuid.uuid4(),
        )
        assert request.command_snapshot_encrypted is not None

        raw = json.loads(decrypt(request.command_snapshot_encrypted))

        assert ("guide_url" in raw) is stored
        assert load_snapshot(request).guide_url == guide

    async def test_prompt_requires_account(
        self,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
    ) -> None:
        command_task.llm_account_id = None
        await db_session.commit()
        with pytest.raises(ValidationError):
            await enqueue_command(
                db_session,
                task=command_task,
                requested_by=command_task.created_by,
                invocation="/review",
                client_request_id=uuid.uuid4(),
            )

    async def test_usage_deduplicates_links_and_calls(
        self,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
    ) -> None:
        db_session.add(
            TaskLibraryPrompt(
                task_id=command_task.id, node_id=command_node.id, added_by=command_task.created_by
            )
        )
        await db_session.flush()
        for _ in range(2):
            await enqueue_command(
                db_session,
                task=command_task,
                requested_by=command_task.created_by,
                invocation="/review",
                client_request_id=uuid.uuid4(),
            )
        assert dict(await count_library_prompt_usage(db_session))[command_node.id] == 1
        second = await make_task(
            db_session,
            created_by=command_task.created_by,
            status=TaskStatus.IN_PROGRESS,
            llm_account_id=command_task.llm_account_id,
        )
        await enqueue_command(
            db_session,
            task=second,
            requested_by=second.created_by,
            invocation="/review",
            client_request_id=uuid.uuid4(),
        )
        assert dict(await count_library_prompt_usage(db_session))[command_node.id] == 2

    @pytest.mark.parametrize("language", [ScriptLanguage.BASH, ScriptLanguage.PYTHON])
    async def test_real_script_arguments(
        self,
        *,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
        language: ScriptLanguage,
        redis_client: Redis,
        tmp_path: Path,
    ) -> None:
        command_task.llm_account_id = None
        command_node.node_type = NodeType.SCRIPT
        command_node.prompt_template = None
        command_node.script_language = language
        command_node.script_content = (
            'printf "%s\\n" "$1" "$2" "$TRACKER_COMMAND_ARGUMENTS"'
            if language is ScriptLanguage.BASH
            else (
                "import os, sys\nprint(sys.argv[1]); print(sys.argv[2]); "
                'print(os.environ["TRACKER_COMMAND_ARGUMENTS"])'
            )
        )
        await db_session.commit()
        invocation = '/review "two words" "$(touch /tmp/never-execute)"'
        await enqueue_command(
            db_session,
            task=command_task,
            requested_by=command_task.created_by,
            invocation=invocation,
            client_request_id=uuid.uuid4(),
        )
        repos_path = tmp_path / command_task.code
        repos_path.mkdir()
        await process_manual_queue_once(
            db_session,
            task=command_task,
            claude_session=ClaudeCodeSession(FakeClaudeAgentClient(messages_per_query=[])),
            repos_path=repos_path,
            redis_client=redis_client,
        )
        log = (
            await db_session.scalars(sa.select(NodeLog).where(NodeLog.task_id == command_task.id))
        ).one()
        assert log.status == NodeLogStatus.SUCCESS
        assert (
            log.script_stdout
            == 'two words\n$(touch /tmp/never-execute)\n"two words" "$(touch /tmp/never-execute)"\n'
        )
        assert log.command_name == "review"

    @pytest.mark.parametrize("status", [TaskStatus.NEW, TaskStatus.DONE, TaskStatus.FAILED])
    async def test_inactive_task(
        self,
        db_session: AsyncSession,
        command_task: Task,
        command_node: Node,
        status: TaskStatus,
    ) -> None:
        command_task.status = status
        await db_session.commit()
        with pytest.raises(ConflictError):
            await enqueue_command(
                db_session,
                task=command_task,
                requested_by=command_task.created_by,
                invocation="/review",
                client_request_id=uuid.uuid4(),
            )
