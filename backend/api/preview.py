"""Предпросмотр рендеринга шаблонных переменных (раздел 5.1 ТЗ).

"Функция предпросмотра рендеринга обязательна для всех трёх мест ввода"
(конструктор пайплайна, библиотека промтов, свободный ввод) — один
эндпоинт, различаемый `scope`, вместо трёх копий одной и той же логики.

Полный рендер с реальными значениями возможен только в контексте
существующей задачи (`{{task.*}}`/`{{env.*}}` резолвятся из строк БД) —
без `task_id` эндпоинт лишь проверяет доступность переменных
(`validate_template_variables`, та же проверка, что и при сохранении) и
возвращает исходный текст без подстановки. Значения секретных переменных
показываются замаскированными (раздел 19.4).
"""

from __future__ import annotations

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.schemas import TemplatePreviewRequest, TemplatePreviewResponse
from db.models.enums import NodeLogTriggerType
from db.models.logs import NodeLog
from db.models.users import User
from db.session import get_session
from services.access import get_node_for_user, get_pipeline_for_user, get_task_for_user
from services.errors import ValidationError
from services.manual_queue import render_freeform_prompt
from services.pipeline_validation import PipelinePosition, pipeline_position
from services.template_context import render_for_task
from services.templating import RenderScope, validate_template_variables

router = APIRouter(prefix="/templates", tags=["templates"])

_SCOPE_BY_VALUE = {scope.value: scope for scope in RenderScope}


async def _pipeline_position(
    db_session: AsyncSession,
    *,
    body: TemplatePreviewRequest,
    user: User,
) -> PipelinePosition:
    """
    Раздел 5.1: предпросмотр ноды пайплайна видит те же предыдущие ноды, что
    и проверка при сохранении. Без пайплайна позиция пустая.
    """
    node = await get_node_for_user(db_session, body.node_id, user=user) if body.node_id else None
    pipeline_id = body.pipeline_id or (node.pipeline_id if node is not None else None)
    if pipeline_id is None:
        return PipelinePosition()
    await get_pipeline_for_user(db_session, pipeline_id, user=user)
    order_index = body.order_index
    if order_index is None and node is not None:
        order_index = node.order_index
    return await pipeline_position(
        db_session,
        pipeline_id=pipeline_id,
        order_index=order_index,
        node=node,
    )


@router.post("/preview", response_model=TemplatePreviewResponse)
async def preview_template(
    body: TemplatePreviewRequest,
    db_session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> TemplatePreviewResponse:
    scope = _SCOPE_BY_VALUE.get(body.scope)
    if scope is None:
        raise ValidationError(f"Неизвестный scope предпросмотра: {body.scope}")

    position = PipelinePosition()
    if scope is RenderScope.PIPELINE:
        position = await _pipeline_position(db_session, body=body, user=current_user)

    if body.task_id is None:
        validate_template_variables(
            body.text,
            scope=scope,
            preceding_node_types=position.preceding_node_types,
            current_node_llm_output_last_n=position.llm_output_last_n,
        )
        return TemplatePreviewResponse(rendered_text=body.text)

    task = await get_task_for_user(db_session, body.task_id, user=current_user)

    if scope is RenderScope.FREEFORM:
        # Раздел 8.2: предпросмотр показывает ровно то, что уйдёт в сессию.
        validate_template_variables(body.text, scope=scope)
        rendered = await render_freeform_prompt(db_session, task=task, text=body.text)
        return TemplatePreviewResponse(rendered_text=rendered.display)

    history: list[NodeLog] = []
    if scope is RenderScope.PIPELINE:
        stmt = (
            sa.select(NodeLog)
            .where(
                NodeLog.task_id == task.id,
                NodeLog.trigger_type == NodeLogTriggerType.PIPELINE,
            )
            .order_by(NodeLog.started_at, NodeLog.id)
        )
        history = list((await db_session.execute(stmt)).scalars().all())

    rendered_text = await render_for_task(
        db_session,
        task,
        body.text,
        history=history,
        last_n=position.llm_output_last_n,
    )
    return TemplatePreviewResponse(rendered_text=rendered_text.display)
