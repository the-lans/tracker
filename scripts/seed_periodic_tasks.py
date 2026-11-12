"""Первичное заполнение таблицы `periodic_tasks` (раздел 16.2 ТЗ: "seed").

Запуск — на шаге 8 `deploy/install.sh`, до первого входа администратора
(раздел 20.2): записи создаются системой, `updated_by = NULL` (раздел 3.1).

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
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app_logging.config import configure_logging, get_logger  # noqa: E402
from db.models.enums import PeriodicScheduleType  # noqa: E402
from db.models.periodic import PeriodicTask  # noqa: E402
from db.models.settings import (  # noqa: E402
    DEFAULT_NIGHT_WINDOW_START,
    SYSTEM_SETTINGS_ROW_ID,
    SystemSettings,
)
from db.session import async_session_factory  # noqa: E402
from services.periodic_tasks import NIGHT_DISPATCH_TASK  # noqa: E402
from services.task_queue import moscow_cron, night_window_cron  # noqa: E402

configure_logging()
logger = get_logger("seed_periodic_tasks")

_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY
_SUNDAY = 0

# Расписание ночного воркера выводится из начала ночного окна (раздел 16.2).
_NIGHT_SCHEDULE = None
# Раздел 20.4: бэкап — ежедневно в 03:00 МСК, проверка — в воскресенье в 02:00 МСК.
_BACKUP_SCHEDULE = moscow_cron(time(3, 0))
_VERIFY_SCHEDULE = moscow_cron(time(2, 0), weekday=_SUNDAY)

# (name, display_name, description, task_path, расписание): число — интервал
# в секундах, строка — crontab по UTC, _NIGHT_SCHEDULE — от ночного окна.
_SEED_TASKS: list[tuple[str, str, str, str, int | str | None]] = [
    (
        "check_scheduled_tasks_for_autostart",
        "Автозапуск запланированных задач",
        "Ставит в очередь (ready) задачи до запуска с автозапуском и наступившим "
        "scheduled_start_at",
        "tasks.periodic.check_scheduled_tasks_for_autostart",
        5 * _MINUTE,
    ),
    (
        "dispatch_ready_tasks",
        "Дневной воркер очереди",
        "Запускает задачи очереди (ready, в ночном окне и night_worker) в свободные слоты "
        "пользователей",
        "tasks.periodic.dispatch_ready_tasks",
        5 * _MINUTE,
    ),
    (
        NIGHT_DISPATCH_TASK,
        "Ночной воркер очереди",
        "В начале ночного окна запускает задачи очереди, включая night_worker; расписание "
        "задаёт ночное окно в системных настройках",
        "tasks.periodic.dispatch_night_tasks",
        _NIGHT_SCHEDULE,
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
        "measure_volume_usage",
        "Замер места на диске",
        "Считает размер volume с репозиториями, файлами задач, сессиями агентов и "
        "архивом логов для страницы «Мониторинг»",
        "tasks.periodic.measure_volume_usage",
        15 * _MINUTE,
    ),
    (
        "revoke_stale_sshfs_keys",
        "Отзыв неиспользуемых SSH-ключей",
        "Напоминает заменить SSH-ключ SFTP-доступа, не использованный 90 дней",
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
        "Блокирует пользователей (вход и SFTP), чьи email удалены из allowed_emails",
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
    (
        "backup_to_s3",
        "Резервное копирование в S3",
        "Полная зашифрованная копия сервера в S3 (БД, файлы задач, данные агентов, .env) "
        "с ротацией; настройки — в системных настройках",
        "tasks.periodic.backup_to_s3",
        _BACKUP_SCHEDULE,
    ),
    (
        "verify_s3_backup",
        "Проверка восстановления из S3",
        "Скачивает последнюю копию, проверяет контрольные суммы и архивы, восстанавливает "
        "дамп во временный PostgreSQL и сверяет таблицы",
        "tasks.periodic.verify_s3_backup",
        _VERIFY_SCHEDULE,
    ),
]


async def _crontab(db_session: AsyncSession, schedule: int | str | None) -> str | None:
    if isinstance(schedule, int):
        return None
    if isinstance(schedule, str):
        return schedule
    return await _night_crontab(db_session)


async def _night_crontab(db_session: AsyncSession) -> str:
    settings = await db_session.get(SystemSettings, SYSTEM_SETTINGS_ROW_ID)
    start = settings.night_window_start if settings is not None else DEFAULT_NIGHT_WINDOW_START
    return night_window_cron(start)


async def _seed() -> None:
    async with async_session_factory() as db_session:
        created = 0
        for name, display_name, description, task_path, schedule in _SEED_TASKS:
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
                    schedule_type=(
                        PeriodicScheduleType.INTERVAL
                        if isinstance(schedule, int)
                        else PeriodicScheduleType.CRONTAB
                    ),
                    interval_seconds=schedule if isinstance(schedule, int) else None,
                    crontab_expression=await _crontab(db_session, schedule),
                    is_enabled=True,
                    # Создано системой при установке (раздел 3.1).
                    updated_by=None,
                ),
            )
            created += 1
        await db_session.commit()
        logger.info("periodic_tasks_seeded", created=created, total=len(_SEED_TASKS))


if __name__ == "__main__":
    asyncio.run(_seed())
