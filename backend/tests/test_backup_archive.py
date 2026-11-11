"""Архив volume для копии (`services/backup/archive.py`, раздел 20.4 ТЗ)."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from services.backup import archive as archive_module
from services.backup.archive import (
    REASON_CHANGING,
    REASON_LOCKED,
    REASON_UNREADABLE,
    ArchiveOptions,
    archive_directory,
)
from services.backup.components import COMMON_EXCLUDES, COMPONENTS

if TYPE_CHECKING:
    from collections.abc import Callable

_OPTIONS = ArchiveOptions(excludes=COMMON_EXCLUDES, attempts=3, retry_delay_seconds=0)


def _write(root: Path, relative: str, content: str = "data") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _members(path: Path) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(path, "r:gz") as tar:
        return {member.name: member for member in tar.getmembers()}


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "task_repos"
    root.mkdir()
    return root


class TestFormat:
    def test_same_layout_as_tar_c(self, source: Path, tmp_path: Path) -> None:
        """`tar xzf … -C <volume>` из install.sh восстанавливает то же дерево."""
        _write(source, "RR-1/app/main.py", "print(1)")
        _write(source, "RR-1/app/.git/HEAD", "ref: refs/heads/feature/RR-1")
        _write(source, "RR-1/app/.git/objects/ab/cdef", "blob")
        os.symlink("app/main.py", source / "RR-1/link.py")
        (source / "RR-1/app/main.py").chmod(0o750)
        target = tmp_path / "task_repos.tar.gz"

        stats = archive_directory(source, target, component="task_repos", options=_OPTIONS)

        assert (stats.files, stats.skipped) == (3, [])
        restored = tmp_path / "restored"
        restored.mkdir()
        subprocess.run(["tar", "xzf", str(target), "-C", str(restored)], check=True)
        assert (restored / "RR-1/app/main.py").read_text() == "print(1)"
        assert (restored / "RR-1/app/.git/objects/ab/cdef").read_text() == "blob"
        assert os.readlink(restored / "RR-1/link.py") == "app/main.py"
        assert (restored / "RR-1/app/main.py").stat().st_mode & 0o777 == 0o750

    def test_hardlink_counted_once(self, source: Path, tmp_path: Path) -> None:
        original = _write(source, "a.pack", "pack")
        os.link(original, source / "b.pack")
        target = tmp_path / "out.tar.gz"

        stats = archive_directory(source, target, component="task_repos", options=_OPTIONS)

        members = _members(target)
        assert stats.files == 1
        assert sum(member.isreg() for member in members.values()) == 1
        assert sum(member.islnk() for member in members.values()) == 1


class TestExcludes:
    def test_caches_and_git_locks(self, source: Path, tmp_path: Path) -> None:
        _write(source, "RR-1/app/__pycache__/m.cpython-312.pyc")
        _write(source, "RR-1/app/pkg/__pycache__/m.pyc")
        _write(source, "RR-1/cache/plugin.bin")
        _write(source, "RR-1/app/.git/refs/heads/main.lock")
        _write(source, "RR-1/app/Cargo.lock", "[[package]]")
        _write(source, "RR-1/projects/session.jsonl")
        [sessions] = [component for component in COMPONENTS if component.name == "claude_sessions"]
        target = tmp_path / "out.tar.gz"

        archive_directory(
            source,
            target,
            component=sessions.name,
            options=ArchiveOptions(excludes=sessions.all_excludes, retry_delay_seconds=0),
        )

        names = set(_members(target))
        assert "./RR-1/projects/session.jsonl" in names
        # Обычные `*.lock` вне `.git` — данные проекта.
        assert "./RR-1/app/Cargo.lock" in names
        assert not any("__pycache__" in name or "/cache" in name for name in names)
        assert "./RR-1/app/.git/refs/heads/main.lock" not in names


class TestBusyFiles:
    def test_locked_by_git_is_skipped(self, source: Path, tmp_path: Path) -> None:
        _write(source, "RR-1/app/.git/index", "index")
        _write(source, "RR-1/app/.git/index.lock", "")
        target = tmp_path / "out.tar.gz"

        stats = archive_directory(source, target, component="task_repos", options=_OPTIONS)

        assert [(item.path, item.reason) for item in stats.skipped] == [
            ("RR-1/app/.git/index", REASON_LOCKED),
        ]
        assert "./RR-1/app/.git/index" not in _members(target)

    def test_lock_released_while_waiting(
        self,
        source: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write(source, "RR-1/.git/index", "index")
        lock = _write(source, "RR-1/.git/index.lock", "")
        monkeypatch.setattr(
            archive_module._DirectoryArchiver,
            "_pause",
            lambda self: lock.unlink(missing_ok=True),
        )
        target = tmp_path / "out.tar.gz"

        stats = archive_directory(source, target, component="task_repos", options=_OPTIONS)

        assert stats.skipped == []
        assert "./RR-1/.git/index" in _members(target)

    @pytest.mark.parametrize(
        ("changes", "skipped"),
        [(1, False), (2, False), (3, True)],
        ids=["once", "twice", "always"],
    )
    def test_changing_file(
        self,
        source: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        changes: int,
        skipped: bool,
    ) -> None:
        """Файл, который меняется во время чтения, перечитывается; не успокоился — пропуск."""
        log = _write(source, "RR-1/session.jsonl", "line\n")
        original: Callable[..., object] = archive_module._DirectoryArchiver._read_stable
        reads = {"count": 0}

        def read_while_writing(self: object, path: Path) -> object:
            if path == log and reads["count"] < changes:
                reads["count"] += 1
                with log.open("a") as stream:
                    stream.write("more\n")
                os.utime(log, ns=(0, reads["count"]))
                return None
            return original(self, path)

        monkeypatch.setattr(archive_module._DirectoryArchiver, "_read_stable", read_while_writing)
        target = tmp_path / "out.tar.gz"

        stats = archive_directory(source, target, component="claude_sessions", options=_OPTIONS)

        assert [item.reason for item in stats.skipped] == ([REASON_CHANGING] if skipped else [])
        assert ("./RR-1/session.jsonl" in _members(target)) is not skipped

    def test_detects_change_during_read(self, source: Path, tmp_path: Path) -> None:
        path = _write(source, "growing.log", "a" * 10)

        with tarfile.open(tmp_path / "out.tar.gz", "w:gz") as tar:
            archiver = archive_module._DirectoryArchiver(
                tar,
                root=source,
                component="c",
                options=_OPTIONS,
            )
            real_open = Path.open

            def open_and_grow(self: Path, *args: object, **kwargs: object) -> object:
                stream = real_open(self, *args, **kwargs)  # type: ignore[call-overload]
                if self == path:
                    with real_open(path, "a") as appender:
                        appender.write("b")
                return stream

            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(Path, "open", open_and_grow)
                assert archiver._read_stable(path) is None

    @pytest.mark.skipif(os.geteuid() == 0, reason="root читает файлы без прав")
    def test_unreadable_file(self, source: Path, tmp_path: Path) -> None:
        secret = _write(source, "secret.txt")
        secret.chmod(0)
        target = tmp_path / "out.tar.gz"
        try:
            stats = archive_directory(source, target, component="user_files", options=_OPTIONS)
        finally:
            secret.chmod(0o600)

        assert [(item.path, item.reason) for item in stats.skipped] == [
            ("secret.txt", REASON_UNREADABLE),
        ]
