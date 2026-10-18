"""Сборка контекста рендеринга из уже загруженных ORM-объектов (раздел 5 ТЗ).

Не открывает сессию БД самостоятельно (правило C плана реализации) —
принимает уже полученные вызывающим кодом объекты; единственное исключение —
``resolve_env_value``, которому для приоритета "задача > глобально" нужно
обратиться к двум таблицам, и явная передача обеих выборок в каждый вызов
была бы менее читаемой, чем передача сессии.
"""

from __future__ import annotations

import uuid
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import EnvVariableScope
from db.models.env_vars import EnvVariable, TaskEnvVariable
from db.models.logs import NodeLog
from db.models.tasks import Task
from services.crypto import decrypt
from services.templating import VARIABLE_PATTERN, render_template

REPOS_PATH_TEMPLATE = "tracker/repos/{code}/"


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def build_task_context(task: Task) -> dict[str, str]:
    """``{{task.*}}`` — поля таблицы ``tasks`` плюс вычисляемый ``repos_path``."""
    context = {
        "task.id": _stringify(task.id),
        "task.code": _stringify(task.code),
        "task.title": _stringify(task.title),
        "task.description": _stringify(task.description),
        "task.guide_url": _stringify(task.guide_url),
        "task.status": _stringify(task.status),
        "task.pipeline_id": _stringify(task.pipeline_id),
        "task.llm_account_id": _stringify(task.llm_account_id),
        "task.parent_task_id": _stringify(task.parent_task_id),
        "task.use_parent_summary": _stringify(task.use_parent_summary),
        "task.session_id": _stringify(task.session_id),
        "task.current_permission_mode": _stringify(task.current_permission_mode),
        "task.auto_accept_plan": _stringify(task.auto_accept_plan),
        "task.remote_control_status": _stringify(task.remote_control_status),
        "task.scheduled_start_at": _stringify(task.scheduled_start_at),
        "task.auto_start_enabled": _stringify(task.auto_start_enabled),
        "task.created_at": _stringify(task.created_at),
        "task.repos_path": REPOS_PATH_TEMPLATE.format(code=task.code),
    }
    return context


def build_session_context(task: Task) -> dict[str, str]:
    """``{{session.*}}`` — единственная переменная раздела 5."""
    return {"session.id": _stringify(task.session_id)}


def build_node_context(
    history: list[NodeLog],
    *,
    last_n: int | None = None,
) -> dict[str, str]:
    """``{{node.*}}`` — источники по разделу 5, вычисленные из истории задачи.

    ``history`` — записи ``node_logs`` этой задачи, предшествующие текущей
    точке рендеринга, в хронологическом порядке (старые первыми).
    Отсутствующий источник (например, ни одна предыдущая нода не была
    скрипт-нодой) даёт пустую строку, а не ошибку — сама ДОСТУПНОСТЬ
    переменной уже проверена на этапе сохранения (``validate_template_variables``).
    """
    script_output = ""
    llm_output = ""
    user_input = ""
    plan_text = ""
    for entry in history:
        if entry.script_stdout is not None:
            script_output = entry.script_stdout
        if entry.llm_output_text is not None:
            llm_output = entry.llm_output_text
        if entry.user_input_text is not None:
            user_input = entry.user_input_text
        if entry.pending_plan_text is not None:
            plan_text = entry.pending_plan_text

    context = {
        "node.script_output": script_output,
        "node.llm_output": llm_output,
        "node.user_input": user_input,
        "node.plan_text": plan_text,
    }
    if last_n is not None:
        recent_outputs = [entry.llm_output_text for entry in history if entry.llm_output_text]
        context["node.llm_output_last_n"] = "\n\n".join(recent_outputs[-last_n:])
    return context


async def resolve_global_env_value(session: AsyncSession, *, key: str) -> str | None:
    """Значение `env_variables` с `scope = global` — без привязки к задаче.

    Используется вне контекста рендеринга промтов, например для системных
    интеграций уровня всего инстанса (решение №5 плана реализации: токен
    GitLab API — один общий на систему, через `env_variables`).
    """
    global_variable = await session.scalar(
        sa.select(EnvVariable).where(
            EnvVariable.key == key,
            EnvVariable.scope == EnvVariableScope.GLOBAL,
        ),
    )
    if global_variable is None:
        return None
    return decrypt(global_variable.value_encrypted)


async def resolve_env_value(session: AsyncSession, *, task_id: uuid.UUID, key: str) -> str | None:
    """``{{env.VAR_NAME}}`` — приоритет `task_env_variables` над `env_variables` (раздел 5)."""
    task_override = await session.scalar(
        sa.select(TaskEnvVariable).where(
            TaskEnvVariable.task_id == task_id,
            TaskEnvVariable.key == key,
        ),
    )
    if task_override is not None:
        return decrypt(task_override.value_encrypted)

    return await resolve_global_env_value(session, key=key)


async def render_for_task(
    session: AsyncSession,
    task: Task,
    template: str,
    *,
    history: list[NodeLog] | None = None,
    last_n: int | None = None,
) -> str:
    """Полный рендеринг: собирает контекст из всех источников раздела 5 и подставляет.

    Единственная функция, кроме ``resolve_env_value``, которой нужна сессия
    БД — сканирует шаблон на ``{{env.KEY}}`` и резолвит каждую переменную;
    остальной контекст (``task``/``session``/``node``) собирается из уже
    переданных объектов.
    """
    context = {
        **build_task_context(task),
        **build_session_context(task),
        **build_node_context(history or [], last_n=last_n),
    }
    for namespace, key in VARIABLE_PATTERN.findall(template):
        if namespace != "env":
            continue
        value = await resolve_env_value(session, task_id=task.id, key=key)
        context[f"env.{key}"] = value or ""

    return render_template(template, context)
