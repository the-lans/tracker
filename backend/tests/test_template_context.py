import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import (
    EnvVariableScope,
    NodeLogStatus,
    NodeLogTriggerType,
    TaskStatus,
    UserRole,
)
from db.models.env_vars import EnvVariable, TaskEnvVariable
from db.models.logs import NodeLog
from db.models.tasks import Task
from db.models.users import User
from services.crypto import encrypt
from services.template_context import (
    build_node_context,
    build_session_context,
    build_task_context,
    render_for_task,
    resolve_env_value,
)


async def _make_task(session: AsyncSession) -> Task:
    user = User(email=f"{uuid.uuid4()}@example.com", role=UserRole.USER)
    session.add(user)
    await session.flush()
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:5]}",
        title="Починить баг",
        description="Описание задачи",
        created_by=user.id,
        status=TaskStatus.IN_PROGRESS,
        session_id="sess-123",
    )
    session.add(task)
    await session.flush()
    return task


def _global_env_variable(key: str, plaintext_value: str) -> EnvVariable:
    return EnvVariable(
        key=key,
        value_encrypted=encrypt(plaintext_value),
        scope=EnvVariableScope.GLOBAL,
    )


async def test_build_task_context_maps_fields_and_computes_repos_path(
    db_session: AsyncSession,
) -> None:
    task = await _make_task(db_session)

    context = build_task_context(task)

    assert context["task.code"] == task.code
    assert context["task.title"] == "Починить баг"
    assert context["task.status"] == "in_progress"
    assert context["task.repos_path"] == f"tracker/repos/{task.code}/"


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

    assert rendered == f"{task.code} / eu / sess-123"
