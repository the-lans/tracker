"""Guard'ы целостности из раздела 3.2 ТЗ, не выражаемые чистым FK/constraint.

Удаление пайплайна/промта-библиотеки/репозитория, всё ещё используемого
задачей, запрещено на уровне API — вместо удаления предлагается архивация.
Эти функции не удаляют и не архивируют ничего сами — они только проверяют,
можно ли выполнить удаление, и поднимают `ConflictError`, если нет; вызывать
их обязан код эндпоинта удаления (раздел API — этап 12 плана реализации).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.enums import TaskStatus
from db.models.logs import NodeLog
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.repositories import Repository, TemplateMcpServer
from db.models.tasks import Task, TaskRepository
from services.errors import ConflictError

# Репозиторий очищается вручную только в этих двух статусах (CLAUDE.md,
# правило 5) — во всех остальных задача считается "активной" применительно
# к запрету удаления привязанного репозитория (раздел 3.2 ТЗ).
_TERMINAL_TASK_STATUSES = (TaskStatus.DONE, TaskStatus.FAILED)

TEMPLATE_IS_REPOSITORY_DEFAULT = (
    "Шаблон назначен репозиторию по умолчанию — сначала снимите его в репозитории"
)


async def _nodes_are_referenced(
    session: AsyncSession,
    node_ids: sa.Select[uuid.UUID],
) -> bool:
    """
    Хотя бы одна из нод ``node_ids`` привязана к задаче, выполнялась в ней
    или ждёт в очереди её ручных запросов.
    """
    references = (
        sa.select(TaskLibraryPrompt.id).where(TaskLibraryPrompt.node_id.in_(node_ids)),
        sa.select(TaskNode.id).where(TaskNode.node_id.in_(node_ids)),
        sa.select(NodeLog.id).where(NodeLog.node_id.in_(node_ids)),
        sa.select(TaskManualRequestQueue.id).where(TaskManualRequestQueue.node_id.in_(node_ids)),
    )
    stmt = sa.select(sa.exists(sa.union_all(*references).subquery().select()))
    return bool(await session.scalar(stmt))


async def _node_is_referenced(session: AsyncSession, node_id: uuid.UUID) -> bool:
    return await _nodes_are_referenced(session, sa.select(Node.id).where(Node.id == node_id))


async def commit_or_conflict(session: AsyncSession, *, message: str) -> None:
    """
    Коммит удаления, которому мешает ссылка, появившаяся после проверки
    (или не выражаемая проверкой): вместо сырой `IntegrityError` — 409.
    """
    try:
        await session.commit()
    except sa.exc.IntegrityError as exc:
        await session.rollback()
        raise ConflictError(message) from exc


async def ensure_pipeline_deletable(session: AsyncSession, pipeline_id: uuid.UUID) -> None:
    """
    Раздел 3.2: пайплайн, привязанный к задаче или чьи ноды использует
    задача (прежний пайплайн после «Вернуть в новые»), удалить нельзя.
    """
    stmt = sa.select(Task.id).where(Task.pipeline_id == pipeline_id).limit(1)
    pipeline_nodes = sa.select(Node.id).where(Node.pipeline_id == pipeline_id)
    if (await session.execute(stmt)).first() is not None or await _nodes_are_referenced(
        session,
        pipeline_nodes,
    ):
        raise ConflictError(
            "Пайплайн используется хотя бы одной задачей — вместо удаления доступна архивация",
        )


async def ensure_node_deletable(session: AsyncSession, node: Node) -> None:
    """
    Раздел 3.2: ноду, которую использует хотя бы одна задача (привязка,
    история выполнения, очередь), удалить нельзя. Промт библиотеки вместо
    этого архивируется, нода пайплайна — пропускается по умолчанию.
    """
    if not await _node_is_referenced(session, node.id):
        return
    if node.pipeline_id is None:
        raise ConflictError(
            "Системный промт используется задачей — вместо удаления доступна архивация",
        )
    raise ConflictError(
        "Нода используется задачей — удалить её нельзя, включите «Пропуск по умолчанию»",
    )


async def _attached_to_active_task(session: AsyncSession, repository_id: uuid.UUID) -> bool:
    stmt = (
        sa.select(TaskRepository.id)
        .join(Task, Task.id == TaskRepository.task_id)
        .where(
            TaskRepository.repository_id == repository_id,
            Task.status.not_in(_TERMINAL_TASK_STATUSES),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).first() is not None


async def ensure_repository_deletable(session: AsyncSession, repository_id: uuid.UUID) -> None:
    """Запрещает удаление репозитория, привязанного к активной (не терминальной) задаче."""
    if await _attached_to_active_task(session, repository_id):
        raise ConflictError("Репозиторий привязан к активной задаче")


async def ensure_repository_renamable(session: AsyncSession, repository_id: uuid.UUID) -> None:
    """
    Раздел 3.2: имя — каталог клона в директории задачи. Переименование
    репозитория активной задачи увело бы следующий запуск в новый пустой клон,
    а незапушенная работа осталась бы в прежнем каталоге.
    """
    if await _attached_to_active_task(session, repository_id):
        raise ConflictError(
            "Репозиторий привязан к активной задаче — переименовать его можно, "
            "когда задача завершится или упадёт",
        )


async def ensure_llm_account_deletable(session: AsyncSession, llm_account_id: uuid.UUID) -> None:
    """Раздел 3.2: LLM-аккаунт, выбранный хотя бы у одной задачи, удалить нельзя."""
    stmt = sa.select(Task.id).where(Task.llm_account_id == llm_account_id).limit(1)
    if (await session.execute(stmt)).first() is not None:
        raise ConflictError("LLM-аккаунт выбран у задачи — удалить его нельзя")


async def ensure_mcp_server_deletable(session: AsyncSession, mcp_server_id: uuid.UUID) -> None:
    """Раздел 3.2: MCP-сервер, подключённый к шаблону, удалить нельзя."""
    stmt = (
        sa.select(TemplateMcpServer.template_id)
        .where(TemplateMcpServer.mcp_server_id == mcp_server_id)
        .limit(1)
    )
    if (await session.execute(stmt)).first() is not None:
        raise ConflictError(
            "MCP-сервер подключён к шаблону — сначала отключите его в шаблонах",
        )


async def ensure_template_deletable(session: AsyncSession, template_id: uuid.UUID) -> None:
    """Раздел 3.2: шаблон, назначенный репозиторию по умолчанию, удалить нельзя."""
    stmt = sa.select(Repository.id).where(Repository.default_template_id == template_id).limit(1)
    if (await session.execute(stmt)).first() is not None:
        raise ConflictError(TEMPLATE_IS_REPOSITORY_DEFAULT)


async def count_library_prompt_usage(db_session: AsyncSession) -> list[tuple[uuid.UUID, int]]:
    """Раздел 15.5: число задач, к которым привязан каждый промт библиотеки."""
    stmt = (
        sa.select(TaskLibraryPrompt.node_id, sa.func.count(sa.distinct(TaskLibraryPrompt.task_id)))
        .group_by(TaskLibraryPrompt.node_id)
    )
    return [(node_id, int(count)) for node_id, count in (await db_session.execute(stmt)).all()]


def ensure_library_prompt_attachable(node: Node) -> None:
    """Раздел 3.2, 7.2: архивный промт остаётся у прежних задач, но новым не выдаётся."""
    if node.is_archived:
        raise ConflictError("Промт в архиве — добавить его в задачу нельзя")


def ensure_pipeline_attachable(pipeline: Pipeline) -> None:
    """Раздел 3.2: архивный пайплайн к задаче не привязывается."""
    if pipeline.is_archived:
        raise ConflictError("Пайплайн архивирован — разархивируйте его или выберите другой")
