"""ORM-модели (раздел 3 ТЗ).

Импорт всех модулей ниже обязателен здесь (а не только внутри самих
модулей) — это регистрирует их таблицы в ``Base.metadata`` для Alembic
autogenerate (см. ``alembic/env.py``) и для тестовой фикстуры
``run_migrations``.

Модели сознательно не объявляют ``relationship()`` — на этом этапе (раздел 3,
данные без сервисного слоя поверх них) шаблоны обращения к связанным
сущностям ещё не определены; сервисы читают/пишут через явные ``select()``
по внешним ключам. ``relationship()`` добавляется точечно там, где реальный
сервисный код будет в этом нуждаться, а не заранее.
"""

from __future__ import annotations

from db.models.env_vars import EnvVariable, TaskEnvVariable
from db.models.llm import LlmAccount
from db.models.logs import AppLog, NodeLog
from db.models.mcp import McpServer
from db.models.notifications import PushSubscription
from db.models.periodic import PeriodicTask
from db.models.pipelines import Node, Pipeline, TaskNode
from db.models.prompts import TaskLibraryPrompt, TaskManualRequestQueue
from db.models.repositories import Repository, Template, TemplateMcpServer
from db.models.settings import SystemSettings
from db.models.tasks import Task, TaskParentSummary, TaskRepository
from db.models.users import AllowedEmail, User

__all__ = [
    "AllowedEmail",
    "AppLog",
    "EnvVariable",
    "LlmAccount",
    "McpServer",
    "Node",
    "NodeLog",
    "PeriodicTask",
    "Pipeline",
    "PushSubscription",
    "Repository",
    "SystemSettings",
    "Task",
    "TaskEnvVariable",
    "TaskLibraryPrompt",
    "TaskManualRequestQueue",
    "TaskNode",
    "TaskParentSummary",
    "TaskRepository",
    "Template",
    "TemplateMcpServer",
    "User",
]
