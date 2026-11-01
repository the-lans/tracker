"""Перенос истории сессий из каталогов прежних LLM-аккаунтов (раздел 20.6 ТЗ)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from services.session_history_migration import migrate_session_histories
from tests.factories import make_llm_account, make_task, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.tasks import Task

_PROJECT = "-data-repos-RR-1"
_HISTORY = '{"type":"user"}\n'


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    accounts, sessions = tmp_path / "accounts", tmp_path / "sessions"
    monkeypatch.setenv("CLAUDE_SESSIONS_ROOT", str(sessions))
    return accounts, sessions


def _write(path: Path, content: str = _HISTORY) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


async def _task(
    db_session: AsyncSession,
    config_dir: Path,
    *,
    session_id: str | None = None,
) -> Task:
    owner = await make_user(db_session)
    account = await make_llm_account(
        db_session,
        owner_id=owner.id,
        claude_config_dir=str(config_dir),
    )
    return await make_task(
        db_session,
        created_by=owner.id,
        llm_account_id=account.id,
        session_id=session_id if session_id is not None else str(uuid.uuid4()),
    )


def _account_history(config_dir: Path, session_id: str) -> None:
    project = config_dir / "projects" / _PROJECT
    _write(project / f"{session_id}.jsonl")
    _write(project / session_id / "subagents" / "agent-1.jsonl")
    _write(project / f"{uuid.uuid4()}.jsonl")
    _write(config_dir / ".credentials.json", "{}")


def _files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


class TestCopy:
    async def test_only_session_history(
        self,
        db_session: AsyncSession,
        roots: tuple[Path, Path],
    ) -> None:
        accounts, sessions = roots
        task = await _task(db_session, accounts / "main")
        session_id = str(task.session_id)
        _account_history(accounts / "main", session_id)

        result = await migrate_session_histories(db_session, accounts_root=accounts)

        assert (result.migrated_tasks, result.copied_files) == ([task.code], 2)
        assert _files(sessions / task.code) == {
            f"projects/{_PROJECT}/{session_id}.jsonl",
            f"projects/{_PROJECT}/{session_id}/subagents/agent-1.jsonl",
        }

    async def test_idempotent_keeps_newer_history(
        self,
        db_session: AsyncSession,
        roots: tuple[Path, Path],
    ) -> None:
        accounts, sessions = roots
        task = await _task(db_session, accounts / "main")
        session_id = str(task.session_id)
        _account_history(accounts / "main", session_id)
        await migrate_session_histories(db_session, accounts_root=accounts)
        continued = sessions / task.code / "projects" / _PROJECT / f"{session_id}.jsonl"
        _write(continued, _HISTORY * 2)

        result = await migrate_session_histories(db_session, accounts_root=accounts)

        assert (result.migrated_tasks, result.copied_files) == ([], 0)
        assert continued.read_text(encoding="utf-8") == _HISTORY * 2

    async def test_symlink_not_followed(
        self,
        db_session: AsyncSession,
        roots: tuple[Path, Path],
        tmp_path: Path,
    ) -> None:
        accounts, sessions = roots
        task = await _task(db_session, accounts / "main")
        secret = _write(tmp_path / "outside" / "secret.txt", "secret")
        history = accounts / "main" / "projects" / _PROJECT / f"{task.session_id}.jsonl"
        history.parent.mkdir(parents=True)
        history.symlink_to(secret)

        result = await migrate_session_histories(db_session, accounts_root=accounts)

        assert result.copied_files == 0
        assert _files(sessions) == set()


class TestSkipped:
    @pytest.mark.parametrize(
        ("config_dir", "session_id"),
        [
            ("../outside", None),
            ("main", "../../escape"),
            ("empty", None),
        ],
        ids=["outside_root", "unsafe_session_id", "no_projects"],
    )
    async def test_reported(
        self,
        db_session: AsyncSession,
        roots: tuple[Path, Path],
        config_dir: str,
        session_id: str | None,
    ) -> None:
        accounts, sessions = roots
        task = await _task(db_session, accounts / config_dir, session_id=session_id)
        if config_dir != "empty":
            _account_history(accounts / config_dir, str(task.session_id))

        result = await migrate_session_histories(db_session, accounts_root=accounts)

        assert (result.skipped_tasks, result.copied_files) == ([task.code], 0)
        assert not sessions.exists()

    async def test_task_without_session_ignored(
        self,
        db_session: AsyncSession,
        roots: tuple[Path, Path],
    ) -> None:
        accounts, _ = roots
        task = await _task(db_session, accounts / "main")
        _account_history(accounts / "main", str(task.session_id))
        task.session_id = None
        await db_session.flush()

        result = await migrate_session_histories(db_session, accounts_root=accounts)

        assert (result.migrated_tasks, result.skipped_tasks) == ([], [])
