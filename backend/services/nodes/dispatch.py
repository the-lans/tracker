"""Диспетчеризация по `node_type` (раздел 4, 11 ТЗ).

Реализует буквально раздел 4: обычный промт рендерится шаблонизатором,
слэш-команда — никогда. Один явный if/else здесь и есть та самая
"диспетчеризация по node_type", о которой план реализации говорит как о
механизме, обеспечивающем правило раздела 4 (а не отдельная опция ноды).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app_logging.app_logs import write_app_log
from clients.claude_agent import ClaudeCodeSession
from db.models.enums import AppLogLevel, NodeLogStatus, NodeType
from db.models.logs import NodeLog
from services.failure_classification import is_transient_assistant_error
from services.nodes.script import ScriptExecutionResult, run_script_node
from services.template_context import render_for_task, resolve_task_env

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.pipelines import Node
    from db.models.tasks import Task


async def resolve_node_prompt(
    db_session: AsyncSession,
    *,
    node: Node,
    task: Task,
    history: list[NodeLog],
) -> str:
    """Возвращает итоговый текст для отправки в сессию.

    ``slash_command``: `command_invocation` буквально, БЕЗ шаблонизатора
    (раздел 4) — единственная ветка, минующая `render_for_task`.
    """
    if node.node_type is NodeType.SLASH_COMMAND:
        if node.command_invocation is None:
            message = "У ноды slash_command не заполнен command_invocation"
            raise ValueError(message)
        return node.command_invocation

    if node.prompt_template is None:
        message = f"У ноды {node.node_type} не заполнен prompt_template"
        raise ValueError(message)
    return await render_for_task(
        db_session,
        task,
        node.prompt_template,
        history=history,
        last_n=node.llm_output_last_n,
    )


async def resolve_node_prompt_or_none(
    db_session: AsyncSession,
    *,
    node: Node,
    task: Task,
    history: list[NodeLog],
) -> str | None:
    """`None` для `script`-нод (у них нет промта); иначе — `resolve_node_prompt`."""
    if node.node_type is NodeType.SCRIPT:
        return None
    return await resolve_node_prompt(db_session, node=node, task=task, history=history)


async def resolve_script_env_or_none(
    db_session: AsyncSession,
    *,
    node: Node,
    task: Task,
) -> dict[str, str] | None:
    """Переменные окружения задачи — только для `script`-нод (раздел 11.4)."""
    if node.node_type is not NodeType.SCRIPT:
        return None
    return await resolve_task_env(db_session, task_id=task.id)


@dataclass(frozen=True, slots=True)
class NodeExecutionOutcome:
    """
    ``is_transient`` (раздел 17.3) — имеет ли смысл повтор неуспешной попытки;
    ``session_lost`` — процесс CLI упал, и перед повтором сессию нужно
    переподключить.
    """

    success: bool
    llm_output_text: str | None = None
    script_stdout: str | None = None
    script_exit_code: int | None = None
    error_message: str | None = None
    is_transient: bool = True
    session_lost: bool = False


async def record_sdk_failure(
    outcome: NodeExecutionOutcome,
    *,
    task_id: uuid.UUID,
    node_id: uuid.UUID | None,
    source: str,
) -> None:
    """
    Раздел 17.2: ошибка взаимодействия с Claude Agent SDK — падение процесса
    CLI или постоянная ошибка ответа (раздел 17.3) — пишется в `app_logs`.
    Сбои скриптов и таймауты сюда не относятся.
    """
    if outcome.success or (outcome.is_transient and not outcome.session_lost):
        return
    await write_app_log(
        level=AppLogLevel.ERROR,
        source=source,
        message=f"Ошибка Claude Agent SDK: {outcome.error_message}",
        context={
            "node_id": str(node_id) if node_id is not None else None,
            "session_lost": outcome.session_lost,
            "is_transient": outcome.is_transient,
        },
        task_id=task_id,
    )


async def execute_llm_node(claude_session: ClaudeCodeSession, prompt: str) -> NodeExecutionOutcome:
    """Выполняет `plain_prompt`/`slash_command` — единая точка обращения к сессии (раздел 6.2)."""
    turn = await claude_session.send_and_collect_text(prompt)
    if turn.is_error:
        return NodeExecutionOutcome(
            success=False,
            llm_output_text=turn.text,
            error_message=turn.result.result or "Сессия вернула ошибку",
            is_transient=is_transient_assistant_error(turn.assistant_error),
        )
    return NodeExecutionOutcome(success=True, llm_output_text=turn.text)


async def execute_llm_node_with_timeout(
    claude_session: ClaudeCodeSession,
    prompt: str,
    *,
    timeout_seconds: float,
) -> NodeExecutionOutcome:
    """Раздел 3.1: `timeout_seconds` применяется одинаково к нодам пайплайна
    и к запускам из библиотеки, для ЛЮБОГО типа ноды — включая LLM-ноды, не
    только `script`. При истечении таймаута сессия прерывается
    (`abort_turn()`), чтобы не оставлять зависший запрос в SDK и не отдать
    хвост прерванного хода следующему запросу.
    """
    try:
        return await asyncio.wait_for(
            execute_llm_node(claude_session, prompt),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        partial_text = claude_session.take_partial_turn_text()
        await claude_session.abort_turn()
        return NodeExecutionOutcome(
            success=False,
            llm_output_text=partial_text,
            error_message="Превышен таймаут выполнения",
        )


async def execute_script_node(
    node: Node,
    *,
    repos_path: Path,
    runner_image: str | None = None,
    env: Mapping[str, str] | None = None,
) -> NodeExecutionOutcome:
    """
    Выполняет `script` в изолированном Docker-контейнере (раздел 11.4, 19.3).

    ``runner_image`` — образ, выбранный вызывающим кодом при запуске
    (`services/system_settings.py::resolve_runner_image`); ``env`` —
    переменные окружения задачи (`services/template_context.py::resolve_task_env`).
    """
    if node.script_content is None or node.script_language is None:
        message = "У ноды script не заполнены script_content/script_language"
        raise ValueError(message)
    result: ScriptExecutionResult = await run_script_node(
        script_content=node.script_content,
        script_language=node.script_language,
        docker_image=runner_image or node.docker_image,
        repos_path=repos_path,
        timeout_seconds=node.timeout_seconds,
        env=env,
    )
    success = result.exit_code == 0 and not result.timed_out
    error_message = None
    if not success:
        error_message = (
            "Скрипт превысил таймаут" if result.timed_out else f"Код возврата {result.exit_code}"
        )
    return NodeExecutionOutcome(
        success=success,
        script_stdout=result.stdout,
        script_exit_code=result.exit_code,
        error_message=error_message,
    )


async def execute_plan_prompt_node(
    claude_session: ClaudeCodeSession,
    prompt: str,
    *,
    db_session: AsyncSession,
    node_log_id: uuid.UUID,
    timeout_seconds: float,
) -> NodeExecutionOutcome:
    """Раздел 9.1: переводит сессию в `permission_mode="plan"` перед отправкой.

    Успех/провал определяется по итоговому статусу СВЯЗАННОЙ записи
    `node_logs` — её обновляет callback разрешений
    (`services/plan_mode.py::build_can_use_tool_callback`) изнутри того же
    вызова `send_and_collect_text`, до возврата отсюда: пока сессия ждёт
    решения пользователя по плану, весь этот вызов остаётся заблокирован
    (раздел 9.2: "Выполнение пайплайна приостанавливается до получения
    решения пользователя") — это и есть структурное следствие модели
    владения сессией одним Celery-таском (архитектурное решение А).
    """
    await claude_session.set_permission_mode("plan")
    outcome = await execute_llm_node_with_timeout(
        claude_session,
        prompt,
        timeout_seconds=timeout_seconds,
    )
    if not outcome.success:
        return outcome

    # Решение по плану записал callback разрешений в своей сессии БД — читаем
    # актуальное состояние, а не объект из карты этой сессии.
    node_log = await db_session.get(NodeLog, node_log_id, populate_existing=True)
    plan_accepted = node_log is not None and node_log.status is NodeLogStatus.SUCCESS
    if not plan_accepted:
        return NodeExecutionOutcome(
            success=False,
            llm_output_text=outcome.llm_output_text,
            error_message="План не был принят (ExitPlanMode не подтверждён)",
        )
    return outcome


async def execute_node(
    node: Node,
    *,
    prompt: str | None,
    claude_session: ClaudeCodeSession,
    repos_path: Path,
    timeout_seconds: float,
    db_session: AsyncSession | None = None,
    node_log_id: uuid.UUID | None = None,
    runner_image: str | None = None,
    script_env: Mapping[str, str] | None = None,
) -> NodeExecutionOutcome:
    """Единая точка диспетчеризации по `node_type` (раздел 11.1: "тип ноды
    определяет способ выполнения, но не создаёт отдельную сущность").

    Общая для пайплайна (раздел 11.7 — с retry) и библиотеки/свободного
    промта (раздел 7.4/8 — без retry): решение "повторять ли" принимает
    вызывающий код, эта функция выполняет ровно одну попытку.

    ``db_session``/``node_log_id`` нужны ТОЛЬКО для `plan_prompt` (раздел
    9.5: он существует исключительно внутри пайплайна, поэтому только
    `services/pipeline_orchestrator.py` передаёт эти аргументы).
    """
    if node.node_type is NodeType.SCRIPT:
        return await execute_script_node(
            node,
            repos_path=repos_path,
            runner_image=runner_image,
            env=script_env,
        )
    if prompt is None:
        message = f"Для ноды типа {node.node_type} не передан prompt"
        raise ValueError(message)
    if node.node_type is NodeType.PLAN_PROMPT:
        if db_session is None or node_log_id is None:
            message = "plan_prompt требует db_session и node_log_id"
            raise ValueError(message)
        return await execute_plan_prompt_node(
            claude_session,
            prompt,
            db_session=db_session,
            node_log_id=node_log_id,
            timeout_seconds=timeout_seconds,
        )
    return await execute_llm_node_with_timeout(
        claude_session,
        prompt,
        timeout_seconds=timeout_seconds,
    )
