"""Первичное заполнение таблицы `periodic_tasks` (раздел 16.2 ТЗ: "seed").

Запуск (после первого входа администратора — раздел 19.1: первый
зарегистрированный пользователь получает роль admin):

    backend/.venv/bin/python scripts/seed_periodic_tasks.py

Идемпотентен: у уже существующих по `name` записей обновляет только
название и описание — их задаёт код, а не администратор. Расписание и
включение не трогает: администратор мог изменить их через UI (раздел 16.1),
повторный запуск не должен это перезаписывать.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import sqlalchemy as sa  # noqa: E402

from app_logging.config import configure_logging, get_logger  # noqa: E402
from db.models.enums import PeriodicScheduleType, UserRole  # noqa: E402
from db.models.periodic import PeriodicTask  # noqa: E402
from db.models.users import User  # noqa: E402
from db.session import async_session_factory  # noqa: E402

configure_logging()
logger = get_logger("seed_periodic_tasks")

_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY

# (name, display_name, description, task_path, interval_seconds)
_SEED_TASKS: list[tuple[str, str, str, str, int]] = [
    (
        "check_scheduled_tasks_for_autostart",
        "Автозапуск запланированных задач",
        "Находит задачи со статусом new, auto_start_enabled=true и наступившим scheduled_start_at",
        "tasks.periodic.check_scheduled_tasks_for_autostart",
        5 * _MINUTE,
    ),
    (
        "check_llm_account_limits",
        "Проверка лимитов LLM-аккаунтов",
        "Возвращает в active LLM-аккаунты, у которых истекло окно лимита",
        "tasks.periodic.check_llm_account_limits",
        5 * _MINUTE,
    ),
    (
        "cleanup_stale_worktrees",
        "Напоминание об очистке директорий",
        "Находит задачи в терминальном статусе с неочищенной директорией",
        "tasks.periodic.cleanup_stale_worktrees",
        _DAY,
    ),
    (
        "detect_awaiting_input_timeout",
        "Таймаут ожидания ввода",
        "Повторно уведомляет автора задачи, ожидающей решения дольше порога",
        "tasks.periodic.detect_awaiting_input_timeout",
        _HOUR,
    ),
    (
        "sync_gitlab_merge_status",
        "Синхронизация статуса MR",
        "Обновляет task_repositories.merge_status по данным GitLab API",
        "tasks.periodic.sync_gitlab_merge_status",
        10 * _MINUTE,
    ),
    (
        "rebase_child_branches_on_parent_merge",
        "Ребейз дочерних веток",
        "Инициирует ребейз дочерних веток при смердже родительской",
        "tasks.periodic.rebase_child_branches_on_parent_merge",
        10 * _MINUTE,
    ),
    (
        "purge_orphaned_docker_containers",
        "Очистка зависших контейнеров",
        "Останавливает зависшие контейнеры script-нод",
        "tasks.periodic.purge_orphaned_docker_containers",
        15 * _MINUTE,
    ),
    (
        "purge_orphaned_playwright_processes",
        "Очистка осиротевших процессов браузера",
        "Находит и завершает осиротевшие процессы Playwright/аналогичных MCP-инструментов",
        "tasks.periodic.purge_orphaned_playwright_processes",
        15 * _MINUTE,
    ),
    (
        "rotate_task_logs",
        "Ротация логов задач",
        "Выгружает старые записи node_logs выполненных задач в архив и удаляет их из БД",
        "tasks.periodic.rotate_task_logs",
        _WEEK,
    ),
    (
        "revoke_stale_sshfs_keys",
        "Отзыв неиспользуемых SSH-ключей",
        "Помечает неиспользуемые SSH-ключи sshfs-доступа для ротации",
        "tasks.periodic.revoke_stale_sshfs_keys",
        _DAY,
    ),
    (
        "health_check_mcp_servers",
        "Проверка доступности MCP-серверов",
        "Обновляет mcp_servers.is_healthy",
        "tasks.periodic.health_check_mcp_servers",
        10 * _MINUTE,
    ),
    (
        "deprovision_inactive_users",
        "Деактивация неактивных пользователей",
        "Блокирует os_username для email, удалённых из allowed_emails",
        "tasks.periodic.deprovision_inactive_users",
        _DAY,
    ),
    (
        "check_remote_control_bridges",
        "Проверка моста удалённого управления",
        "Проверяет и восстанавливает мост /remote-control для активных задач",
        "tasks.periodic.check_remote_control_bridges",
        2 * _MINUTE,
    ),
    (
        "expire_stale_manual_queue_requests",
        "Истечение зависших ручных запросов",
        "Отменяет запросы в task_manual_request_queue, зависшие в очереди дольше порога",
        "tasks.periodic.expire_stale_manual_queue_requests",
        15 * _MINUTE,
    ),
]


async def _seed() -> None:
    async with async_session_factory() as db_session:
        admin = await db_session.scalar(
            sa.select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at).limit(1),
        )
        if admin is None:
            logger.error("no_admin_user_found")
            message = (
                "В системе ещё нет ни одного администратора (раздел 19.1) — "
                "выполните первый вход через Google OAuth, затем повторите запуск."
            )
            raise RuntimeError(message)

        created = 0
        for name, display_name, description, task_path, interval_seconds in _SEED_TASKS:
            existing = await db_session.scalar(
                sa.select(PeriodicTask).where(PeriodicTask.name == name),
            )
            if existing is not None:
                existing.display_name = display_name
                existing.description = description
                continue
            db_session.add(
                PeriodicTask(
                    id=uuid.uuid4(),
                    name=name,
                    display_name=display_name,
                    description=description,
                    task_path=task_path,
                    schedule_type=PeriodicScheduleType.INTERVAL,
                    interval_seconds=interval_seconds,
                    is_enabled=True,
                    updated_by=admin.id,
                ),
            )
            created += 1
        await db_session.commit()
        logger.info("periodic_tasks_seeded", created=created, total=len(_SEED_TASKS))


if __name__ == "__main__":
    asyncio.run(_seed())
