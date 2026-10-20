"""
Ротация истории выполнения (раздел 16.2 ТЗ, `rotate_task_logs`).

Решение 2026-10-20: записи `node_logs` завершённых задач старше порога
выгружаются в сжатые JSONL-файлы в volume `log_archive` и удаляются из БД.
Удаление идёт только после того, как файл полностью записан на диск:
сбой записи не теряет историю, а повторный запуск подхватит те же записи.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from app_logging.config import get_logger
from db.models.logs import NodeLog
from db.models.tasks import Task
from services.maintenance_tasks import (
    DEFAULT_LOG_ROTATION_THRESHOLD_DAYS,
    find_node_logs_eligible_for_rotation,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("log_rotation")

_ARCHIVE_ROOT_ENV_VAR = "TRACKER_LOG_ARCHIVE_ROOT"
_DEFAULT_ARCHIVE_ROOT = "tracker/log-archive"
# Записей за один запуск: еженедельная задача доберёт остаток в следующий раз.
ROTATION_BATCH_SIZE = 5000
_FILE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def resolve_archive_root() -> Path:
    """Каталог архива — volume `log_archive` (раздел 20.4)."""
    return Path(os.environ.get(_ARCHIVE_ROOT_ENV_VAR, _DEFAULT_ARCHIVE_ROOT))


@dataclass(slots=True)
class RotationResult:
    archived_files: list[Path] = field(default_factory=list)
    deleted_count: int = 0


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def _serialize(node_log: NodeLog) -> dict[str, Any]:
    return {
        column.key: _serialize_value(getattr(node_log, column.key))
        for column in sa.inspect(NodeLog).columns
    }


def _write_archive(path: Path, records: list[dict[str, Any]]) -> None:
    """Временный файл, `fsync`, затем переименование — файл либо целый, либо его нет."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


async def rotate_node_logs(
    db_session: AsyncSession,
    *,
    archive_root: Path,
    now: datetime,
    threshold_days: int = DEFAULT_LOG_ROTATION_THRESHOLD_DAYS,
    batch_size: int = ROTATION_BATCH_SIZE,
) -> RotationResult:
    """Выгружает и удаляет записи по одной задаче за раз — один файл на задачу."""
    eligible_ids = await find_node_logs_eligible_for_rotation(
        db_session,
        now=now,
        threshold_days=threshold_days,
        limit=batch_size,
    )
    result = RotationResult()
    if not eligible_ids:
        return result
    stmt = (
        sa.select(NodeLog, Task.code)
        .join(Task, Task.id == NodeLog.task_id)
        .where(NodeLog.id.in_(eligible_ids))
        .order_by(NodeLog.task_id, NodeLog.started_at, NodeLog.id)
    )
    by_task: dict[str, list[NodeLog]] = {}
    for node_log, task_code in (await db_session.execute(stmt)).all():
        by_task.setdefault(task_code, []).append(node_log)

    stamp = now.strftime(_FILE_TIMESTAMP_FORMAT)
    for task_code, node_logs in by_task.items():
        path = archive_root / task_code / f"node_logs-{stamp}-{uuid.uuid4().hex[:8]}.jsonl.gz"
        records = [_serialize(node_log) for node_log in node_logs]
        await asyncio.to_thread(_write_archive, path, records)
        await db_session.execute(
            sa.delete(NodeLog).where(NodeLog.id.in_([node_log.id for node_log in node_logs])),
        )
        await db_session.commit()
        result.archived_files.append(path)
        result.deleted_count += len(node_logs)
        logger.info(
            "node_logs_archived",
            task_code=task_code,
            path=str(path),
            count=len(node_logs),
        )
    return result
