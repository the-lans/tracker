"""
Тестовые данные стенда ручного E2E-тестирования (docs/qa_e2e_manual.md,
разделы 1.3 и 2): администратор, LLM-аккаунт, репозиторий qa-calc,
переменные окружения, промты библиотеки, интеграции с моком Jira/GitLab и
эталонный пайплайн «QA: фича с тестами».

Запускается из `scripts/qa/stand.sh data` в контейнере backend. Идемпотентен:
существующие записи (по e-mail, каталогу, имени, ключу) не дублируются и не
меняются — повторный запуск добавляет только недостающее.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app_logging.config import configure_logging, get_logger  # noqa: E402
from db.models.enums import EnvVariableScope, NodeType, ScriptLanguage, UserRole  # noqa: E402
from db.models.env_vars import EnvVariable  # noqa: E402
from db.models.llm import LlmAccount  # noqa: E402
from db.models.pipelines import Node, Pipeline  # noqa: E402
from db.models.repositories import Repository  # noqa: E402
from db.models.users import AllowedEmail, User  # noqa: E402
from db.session import async_session_factory  # noqa: E402
from services.crypto import encrypt  # noqa: E402
from services.llm_accounts import validated_config_dir  # noqa: E402
from services.pipeline_validation import validate_node_shape, validate_pipeline_templates  # noqa: E402
from services.repository_validation import validate_git_url, validate_repository_name  # noqa: E402
from services.system_settings import (  # noqa: E402
    get_system_settings,
    resolve_node_execution_defaults,
    update_integrations,
)

configure_logging()
logger = get_logger("seed_qa_data")

PIPELINE_DIR = Path(__file__).resolve().parent / "pipeline"
REPOSITORY_NAME = "qa-calc"
GIT_URL = "ssh://git@qa-git/srv/git/qa/qa-calc.git"
MOCKS_URL = "http://qa-mocks:8090"
GITLAB_TOKEN = "qa-token"  # noqa: S105 — мок принимает любой токен
LLM_ACCOUNT_LABEL = "QA"
PIPELINE_NAME = "QA: фича с тестами"
TESTS_MAX_RETRIES = 2
TESTS_RETRY_DELAY_SECONDS = 5

ENV_VARIABLES = (
    ("QA_GREETING", "Привет из QA", False),
    ("QA_TOKEN", "qa-secret-123", True),
)


@dataclass(frozen=True, slots=True)
class NodeSpec:
    name: str
    node_type: NodeType
    description: str | None = None
    prompt_template: str | None = None
    command_invocation: str | None = None
    script_language: ScriptLanguage | None = None
    script_file: str | None = None
    max_retries: int | None = None
    retry_base_delay_seconds: int | None = None


LIBRARY_NODES = (
    NodeSpec(
        name="Ревью изменений",
        node_type=NodeType.PLAIN_PROMPT,
        description="Ревью изменений ветки задачи: риски и пропущенные тесты",
        prompt_template=(
            "Сделай ревью изменений в ветке {{task.code}}: перечисли риски и пропущенные тесты"
        ),
    ),
    NodeSpec(
        name="Статус репозитория",
        node_type=NodeType.SLASH_COMMAND,
        description="Слэш-команда /status в сессии задачи",
        command_invocation="/status",
    ),
)

PIPELINE_NODES = (
    NodeSpec(
        name="Сбор контекста",
        node_type=NodeType.SCRIPT,
        script_language=ScriptLanguage.BASH,
        script_file="collect_context.sh",
    ),
    NodeSpec(
        name="План",
        node_type=NodeType.PLAN_PROMPT,
        prompt_template=(
            "Спланируй добавление в `calc.py` функции `divide(left, right)`: при делении на "
            "ноль — `ZeroDivisionError` с понятным сообщением; нужны тесты в `test_calc.py`. "
            "Контекст репозитория: {{node.script_output}}"
        ),
    ),
    NodeSpec(
        name="Реализация",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template=(
            "Реализуй задачу {{task.code}} по утверждённому плану: {{node.plan_text}}. "
            "В README добавь строку: {{env.QA_GREETING}}. Запусти `python3 -m unittest -v`, "
            "затем закоммить изменения в текущую ветку: `git -c user.name=\"QA Agent\" "
            "-c user.email=qa-agent@example.com commit -am \"feat: add divide\"`."
        ),
    ),
    NodeSpec(
        name="Тесты",
        node_type=NodeType.SCRIPT,
        script_language=ScriptLanguage.PYTHON,
        script_file="run_tests.py",
        max_retries=TESTS_MAX_RETRIES,
        retry_base_delay_seconds=TESTS_RETRY_DELAY_SECONDS,
    ),
    NodeSpec(name="Очистка контекста", node_type=NodeType.CLEAR_CONTEXT),
    NodeSpec(
        name="Итог",
        node_type=NodeType.PLAIN_PROMPT,
        prompt_template=(
            "Кратко перечисли, что изменено в ветке задачи {{task.code}}, "
            "по выводу тестов: {{node.script_output}}"
        ),
    ),
)


async def _admin(db_session: AsyncSession, email: str) -> User:
    """Вход через Google найдёт эту запись по e-mail (раздел 19.1)."""
    allowed = sa.select(AllowedEmail.id).where(AllowedEmail.email == email)
    if await db_session.scalar(allowed) is None:
        db_session.add(AllowedEmail(email=email))
    user = await db_session.scalar(sa.select(User).where(User.email == email))
    if user is None:
        user = User(email=email, role=UserRole.ADMIN, is_active=True)
        db_session.add(user)
        await db_session.flush()
        logger.info("qa_admin_created", email=email)
    return user


async def _llm_account(db_session: AsyncSession, *, owner: User, config_dir: str) -> None:
    path = await _existing_or_validated_dir(db_session, config_dir)
    if path is None:
        return
    db_session.add(LlmAccount(label=LLM_ACCOUNT_LABEL, claude_config_dir=path, created_by=owner.id))
    logger.info("qa_llm_account_created", claude_config_dir=path)


async def _existing_or_validated_dir(db_session: AsyncSession, config_dir: str) -> str | None:
    """`None` — аккаунт с этим каталогом уже есть."""
    exists = sa.select(LlmAccount.id).where(LlmAccount.claude_config_dir == config_dir.rstrip("/"))
    if await db_session.scalar(exists) is not None:
        return None
    return await validated_config_dir(db_session, config_dir)


async def _repository(db_session: AsyncSession, deploy_key: str) -> None:
    exists = sa.select(Repository.id).where(Repository.name == REPOSITORY_NAME)
    if await db_session.scalar(exists) is not None:
        return
    db_session.add(
        Repository(
            name=validate_repository_name(REPOSITORY_NAME),
            git_url=validate_git_url(GIT_URL),
            deploy_key_encrypted=encrypt(deploy_key),
        ),
    )
    logger.info("qa_repository_created", name=REPOSITORY_NAME)


async def _env_variables(db_session: AsyncSession) -> None:
    for key, value, is_secret in ENV_VARIABLES:
        exists = sa.select(EnvVariable.id).where(
            EnvVariable.key == key,
            EnvVariable.scope == EnvVariableScope.GLOBAL,
        )
        if await db_session.scalar(exists) is not None:
            continue
        db_session.add(
            EnvVariable(
                key=key,
                value_encrypted=encrypt(value),
                is_secret=is_secret,
                scope=EnvVariableScope.GLOBAL,
            ),
        )
        logger.info("qa_env_variable_created", key=key)


async def _integrations(db_session: AsyncSession) -> None:
    settings = await get_system_settings(db_session)
    if settings.jira_url and settings.gitlab_url:
        return
    await update_integrations(
        db_session,
        gitlab_url=settings.gitlab_url or MOCKS_URL,
        gitlab_token=None if settings.gitlab_token_encrypted else GITLAB_TOKEN,
        jira_url=settings.jira_url or MOCKS_URL,
    )


async def _node(
    db_session: AsyncSession,
    spec: NodeSpec,
    *,
    owner: User,
    pipeline_id: uuid.UUID | None = None,
    order_index: int | None = None,
) -> Node:
    defaults = await resolve_node_execution_defaults(
        db_session,
        timeout_seconds=None,
        max_retries=spec.max_retries,
        retry_base_delay_seconds=spec.retry_base_delay_seconds,
    )
    script = (PIPELINE_DIR / spec.script_file).read_text() if spec.script_file else None
    node = Node(
        pipeline_id=pipeline_id,
        order_index=order_index,
        name=spec.name,
        description=spec.description,
        node_type=spec.node_type,
        prompt_template=spec.prompt_template,
        command_invocation=spec.command_invocation,
        script_language=spec.script_language,
        script_content=script,
        timeout_seconds=defaults.timeout_seconds,
        max_retries=defaults.max_retries,
        retry_base_delay_seconds=defaults.retry_base_delay_seconds,
        is_skipped=False,
        is_library_item=pipeline_id is None,
        is_archived=False,
        created_by=owner.id,
    )
    validate_node_shape(node)
    db_session.add(node)
    await db_session.flush()
    return node


async def _library(db_session: AsyncSession, owner: User) -> None:
    for spec in LIBRARY_NODES:
        exists = sa.select(Node.id).where(Node.is_library_item, Node.name == spec.name)
        if await db_session.scalar(exists) is None:
            await _node(db_session, spec, owner=owner)
            logger.info("qa_library_prompt_created", name=spec.name)


async def _pipeline(db_session: AsyncSession, owner: User) -> None:
    exists = sa.select(Pipeline.id).where(Pipeline.name == PIPELINE_NAME, ~Pipeline.is_archived)
    if await db_session.scalar(exists) is not None:
        return
    pipeline = Pipeline(name=PIPELINE_NAME, is_archived=False, created_by=owner.id)
    db_session.add(pipeline)
    await db_session.flush()
    for order_index, spec in enumerate(PIPELINE_NODES):
        await _node(db_session, spec, owner=owner, pipeline_id=pipeline.id, order_index=order_index)
    await validate_pipeline_templates(db_session, pipeline.id)
    logger.info("qa_pipeline_created", name=PIPELINE_NAME, nodes=len(PIPELINE_NODES))


async def _seed(*, admin_email: str, claude_config_dir: str, deploy_key: str) -> None:
    async with async_session_factory() as db_session:
        owner = await _admin(db_session, admin_email)
        await _llm_account(db_session, owner=owner, config_dir=claude_config_dir)
        await _repository(db_session, deploy_key)
        await _env_variables(db_session)
        await _library(db_session, owner)
        await _pipeline(db_session, owner)
        await db_session.commit()
        await _integrations(db_session)
    logger.info("qa_data_seeded", admin_email=admin_email)


def main() -> None:
    parser = argparse.ArgumentParser(description="Тестовые данные стенда ручного E2E")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--claude-config-dir", required=True)
    parser.add_argument("--deploy-key", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(
        _seed(
            admin_email=args.admin_email,
            claude_config_dir=args.claude_config_dir,
            deploy_key=args.deploy_key.read_text(),
        ),
    )


if __name__ == "__main__":
    main()
