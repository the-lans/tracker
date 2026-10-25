import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import (
    EnvVariableScope,
    NodeLogStatus,
    NodeLogTriggerType,
    RepositoryRole,
    TaskStatus,
)
from db.models.env_vars import EnvVariable, TaskEnvVariable
from db.models.logs import NodeLog
from db.models.repositories import Repository
from db.models.tasks import Task, TaskRepository
from services.crypto import encrypt
from services.errors import ValidationError
from services.template_context import (
    build_node_context,
    build_session_context,
    build_task_context,
    ensure_no_repository_env_conflicts,
    render_for_task,
    resolve_env_value,
    resolve_task_env,
)
from tests.factories import make_task


async def _make_task(session: AsyncSession) -> Task:
    return await make_task(
        session,
        title="Починить баг",
        description="Описание задачи",
        status=TaskStatus.IN_PROGRESS,
        session_id="sess-123",
    )


def _global_env_variable(key: str, plaintext_value: str) -> EnvVariable:
    return EnvVariable(
        key=key,
        value_encrypted=encrypt(plaintext_value),
        scope=EnvVariableScope.GLOBAL,
    )


async def test_build_task_context_maps_fields_and_computes_repos_path(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Раздел 5: `{{task.repos_path}}` и `{{task.artifacts_path}}` — абсолютные пути задачи."""
    monkeypatch.setenv("TRACKER_REPOS_ROOT", "/data/repos")
    monkeypatch.setenv("TRACKER_USER_FILES_ROOT", "/data/user-files")
    task = await _make_task(db_session)
    task.jira_issue_url = "https://jira.example.com/browse/PROJ-1"

    context = build_task_context(task)

    assert context["task.code"] == task.code
    assert context["task.jira_issue_url"] == "https://jira.example.com/browse/PROJ-1"
    assert context["task.title"] == "Починить баг"
    assert context["task.status"] == "in_progress"
    assert context["task.repos_path"] == f"/data/repos/{task.code}/"
    assert context["task.artifacts_path"] == f"/data/user-files/{task.code}/"


async def test_build_session_context_uses_task_session_id(db_session: AsyncSession) -> None:
    task = await _make_task(db_session)

    assert build_session_context(task) == {"session.id": "sess-123"}


def test_build_node_context_picks_last_non_null_value_per_field() -> None:
    history = [
        NodeLog(
            task_id=uuid.uuid4(),
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
            script_stdout="первый вывод",
        ),
        NodeLog(
            task_id=uuid.uuid4(),
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
            llm_output_text="ответ модели",
        ),
        NodeLog(
            task_id=uuid.uuid4(),
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.AWAITING_DECISION,
            user_input_text="принять план",
            pending_plan_text="1. сделать раз\n2. сделать два",
        ),
    ]

    context = build_node_context(history)

    assert context["node.script_output"] == "первый вывод"
    assert context["node.llm_output"] == "ответ модели"
    assert context["node.user_input"] == "принять план"
    assert context["node.plan_text"] == "1. сделать раз\n2. сделать два"


def test_build_node_context_llm_output_last_n_joins_only_last_n() -> None:
    history = [
        NodeLog(
            task_id=uuid.uuid4(),
            trigger_type=NodeLogTriggerType.PIPELINE,
            status=NodeLogStatus.SUCCESS,
            llm_output_text=f"реплика {i}",
        )
        for i in range(5)
    ]

    context = build_node_context(history, last_n=2)

    assert context["node.llm_output_last_n"] == "реплика 3\n\nреплика 4"


async def test_resolve_env_value_prefers_task_override_over_global(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session)
    db_session.add(_global_env_variable("API_URL", "global"))
    db_session.add(
        TaskEnvVariable(task_id=task.id, key="API_URL", value_encrypted=encrypt("override")),
    )
    await db_session.flush()

    assert await resolve_env_value(db_session, task_id=task.id, key="API_URL") == "override"


async def test_resolve_env_value_falls_back_to_global(db_session: AsyncSession) -> None:
    task = await _make_task(db_session)
    db_session.add(_global_env_variable("API_URL", "global"))
    await db_session.flush()

    assert await resolve_env_value(db_session, task_id=task.id, key="API_URL") == "global"


async def test_resolve_env_value_returns_none_when_missing(db_session: AsyncSession) -> None:
    task = await _make_task(db_session)

    assert await resolve_env_value(db_session, task_id=task.id, key="MISSING") is None


async def test_render_for_task_combines_all_sources(db_session: AsyncSession) -> None:
    task = await _make_task(db_session)
    db_session.add(_global_env_variable("REGION", "eu"))
    await db_session.flush()

    rendered = await render_for_task(
        db_session,
        task,
        "{{task.code}} / {{env.REGION}} / {{session.id}}",
    )

    assert rendered.text == f"{task.code} / eu / sess-123"


async def _attach_repository_variable(
    session: AsyncSession,
    task: Task,
    *,
    repository_name: str,
    key: str,
    value: str,
) -> None:
    repository = Repository(
        name=repository_name,
        git_url=f"git@example.com:{repository_name}.git",
        deploy_key_encrypted=encrypt("k"),
    )
    session.add(repository)
    await session.flush()
    session.add_all(
        [
            TaskRepository(
                task_id=task.id,
                repository_id=repository.id,
                role=RepositoryRole.READ_WRITE,
                branch_name=f"feature/{task.code}",
                base_branch="main",
            ),
            EnvVariable(
                key=key,
                value_encrypted=encrypt(value),
                is_secret=False,
                scope=EnvVariableScope.REPOSITORY,
                repository_id=repository.id,
            ),
        ],
    )
    await session.flush()


class TestRepositoryEnvVariables:
    @pytest.mark.parametrize(
        ("levels", "expected"),
        [
            (("task", "repository", "global"), "task"),
            (("repository", "global"), "repository"),
            (("global",), "global"),
        ],
        ids=["task_wins", "repository_over_global", "global_only"],
    )
    async def test_priority(
        self,
        db_session: AsyncSession,
        levels: tuple[str, ...],
        expected: str,
    ) -> None:
        task = await _make_task(db_session)
        if "global" in levels:
            db_session.add(_global_env_variable("API_URL", "global"))
        if "task" in levels:
            db_session.add(
                TaskEnvVariable(task_id=task.id, key="API_URL", value_encrypted=encrypt("task")),
            )
        await db_session.flush()
        if "repository" in levels:
            await _attach_repository_variable(
                db_session,
                task,
                repository_name="backend",
                key="API_URL",
                value="repository",
            )

        assert await resolve_env_value(db_session, task_id=task.id, key="API_URL") == expected

    async def test_other_task_repository_ignored(self, db_session: AsyncSession) -> None:
        task = await _make_task(db_session)
        other = await _make_task(db_session)
        await _attach_repository_variable(
            db_session,
            other,
            repository_name="frontend",
            key="API_URL",
            value="чужой",
        )

        assert await resolve_env_value(db_session, task_id=task.id, key="API_URL") is None

    async def test_conflict_between_repositories(self, db_session: AsyncSession) -> None:
        task = await _make_task(db_session)
        for name in ("backend", "frontend"):
            await _attach_repository_variable(
                db_session,
                task,
                repository_name=name,
                key="API_URL",
                value=name,
            )

        with pytest.raises(ValidationError, match="backend, frontend"):
            await resolve_env_value(db_session, task_id=task.id, key="API_URL")
        with pytest.raises(ValidationError, match="API_URL"):
            await ensure_no_repository_env_conflicts(db_session, task_id=task.id)


class TestResolveTaskEnv:
    """Раздел 11.4: переменные окружения script-контейнера."""

    async def test_levels_override_in_order(self, db_session: AsyncSession) -> None:
        task = await _make_task(db_session)
        db_session.add_all(
            [
                _global_env_variable("API_URL", "global"),
                _global_env_variable("ONLY_GLOBAL", "g"),
                TaskEnvVariable(task_id=task.id, key="API_URL", value_encrypted=encrypt("task")),
            ],
        )
        await db_session.flush()
        await _attach_repository_variable(
            db_session,
            task,
            repository_name="backend",
            key="ONLY_GLOBAL",
            value="repository",
        )

        env = await resolve_task_env(db_session, task_id=task.id)

        assert env == {"API_URL": "task", "ONLY_GLOBAL": "repository"}

    @pytest.mark.parametrize(
        "key",
        ["1BAD", "WITH-DASH", "SPACE KEY"],
        ids=["leading_digit", "dash", "space"],
    )
    async def test_skips_key(self, db_session: AsyncSession, key: str) -> None:
        task = await _make_task(db_session)
        db_session.add(TaskEnvVariable(task_id=task.id, key=key, value_encrypted=encrypt("x")))
        await db_session.flush()

        assert key not in await resolve_task_env(db_session, task_id=task.id)

    async def test_conflict_between_repositories(self, db_session: AsyncSession) -> None:
        task = await _make_task(db_session)
        for name in ("backend", "frontend"):
            await _attach_repository_variable(
                db_session,
                task,
                repository_name=name,
                key="API_URL",
                value=name,
            )

        with pytest.raises(ValidationError, match="API_URL"):
            await resolve_task_env(db_session, task_id=task.id)
