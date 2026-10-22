"""`services/task_artifacts.py` — артефакты задачи (раздел 14.3 ТЗ, решение №18 плана)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from services.errors import NotFoundError, PayloadTooLargeError, ValidationError
from services.task_artifacts import (
    artifact_file,
    delete_artifact,
    list_artifacts,
    max_upload_bytes,
    resolve_entry,
    resolve_inside,
    save_artifact,
    task_artifacts_dir,
    task_artifacts_path,
)

CODE = "RR-30001"


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


class TestPaths:
    def test_dir_inside_root(self, user_files_root: Path) -> None:
        assert task_artifacts_dir(CODE) == user_files_root / CODE
        assert (user_files_root / CODE).is_dir()

    def test_path_is_absolute_with_slash(self, user_files_root: Path) -> None:
        assert task_artifacts_path(CODE) == f"{(user_files_root / CODE).resolve()}/"

    def test_max_upload_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTIFACT_MAX_UPLOAD_MB", "2")
        assert max_upload_bytes() == 2 * 1024 * 1024


class TestResolveInside:
    @pytest.mark.parametrize(
        "relative",
        ["../x", "a/../../x", "/etc/passwd", "a\0b"],
        ids=["parent", "nested_parent", "absolute", "nul"],
    )
    def test_rejects(self, tmp_path: Path, relative: str) -> None:
        with pytest.raises(ValidationError):
            resolve_inside(tmp_path, relative)

    def test_symlink_outside_rejected(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        (base / "link").symlink_to(tmp_path)

        with pytest.raises(ValidationError):
            resolve_inside(base, "link/secret.txt")

    def test_symlink_inside_allowed(self, tmp_path: Path) -> None:
        (tmp_path / "real").mkdir()
        (tmp_path / "alias").symlink_to(tmp_path / "real")

        assert resolve_inside(tmp_path, "alias/f.txt") == (tmp_path / "real" / "f.txt").resolve()

    @pytest.mark.parametrize("relative", ["", "."], ids=["empty", "dot"])
    def test_base_itself(self, tmp_path: Path, relative: str) -> None:
        assert resolve_inside(tmp_path, relative) == tmp_path.resolve()


class TestResolveEntry:
    def test_last_symlink_not_followed(self, tmp_path: Path) -> None:
        (tmp_path / "real").mkdir()
        (tmp_path / "alias").symlink_to(tmp_path / "real")
        (tmp_path / "real" / "link").symlink_to(tmp_path)

        assert resolve_entry(tmp_path, "alias/link") == tmp_path.resolve() / "real" / "link"

    @pytest.mark.parametrize(
        "relative",
        ["", ".", "..", "a/..", "/etc/passwd", "a\0b"],
        ids=["empty", "dot", "parent", "nested_parent", "absolute", "nul"],
    )
    def test_rejects(self, tmp_path: Path, relative: str) -> None:
        with pytest.raises(ValidationError):
            resolve_entry(tmp_path, relative)

    def test_parent_outside_rejected(self, tmp_path: Path) -> None:
        base = tmp_path / "base"
        base.mkdir()
        (base / "out").symlink_to(tmp_path)

        with pytest.raises(ValidationError):
            resolve_entry(base, "out/file.txt")


class TestSave:
    async def test_writes_nested_file(self, user_files_root: Path) -> None:
        info = await save_artifact(CODE, "docs/spec.md", _chunks(b"# ", b"spec"), max_bytes=100)

        assert (user_files_root / CODE / "docs" / "spec.md").read_bytes() == b"# spec"
        assert info.path == "docs/spec.md"
        assert info.size == len(b"# spec")

    async def test_too_large_keeps_previous(self, user_files_root: Path) -> None:
        await save_artifact(CODE, "a.txt", _chunks(b"old"), max_bytes=100)

        with pytest.raises(PayloadTooLargeError):
            await save_artifact(CODE, "a.txt", _chunks(b"12345", b"67890"), max_bytes=8)

        directory = user_files_root / CODE
        assert (directory / "a.txt").read_bytes() == b"old"
        assert sorted(path.name for path in directory.iterdir()) == ["a.txt"]

    @pytest.mark.parametrize("relative", ["", "../escape.txt"], ids=["empty", "escape"])
    async def test_rejects_path(self, relative: str) -> None:
        with pytest.raises(ValidationError):
            await save_artifact(CODE, relative, _chunks(b"x"), max_bytes=100)

    async def test_replaces_symlink_not_target(self, user_files_root: Path) -> None:
        directory = task_artifacts_dir(CODE)
        (directory / "report.txt").write_text("report")
        (directory / "latest").symlink_to("report.txt")

        await save_artifact(CODE, "latest", _chunks(b"new"), max_bytes=100)

        assert not (directory / "latest").is_symlink()
        assert (directory / "latest").read_bytes() == b"new"
        assert (directory / "report.txt").read_text() == "report"

    async def test_rejects_directory(self, user_files_root: Path) -> None:
        (user_files_root / CODE / "dir").mkdir(parents=True)

        with pytest.raises(ValidationError):
            await save_artifact(CODE, "dir", _chunks(b"x"), max_bytes=100)


class TestList:
    def test_files_sorted_without_symlinks(self, user_files_root: Path, tmp_path: Path) -> None:
        directory = task_artifacts_dir(CODE)
        (directory / "b").mkdir()
        (directory / "b" / "two.txt").write_text("2")
        (directory / "one.txt").write_text("1")
        (directory / "outside").symlink_to(tmp_path / "secret.txt")
        (directory / ".tracker-upload-abc").write_text("partial")

        assert [info.path for info in list_artifacts(CODE)] == ["b/two.txt", "one.txt"]

    def test_limited(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("services.task_artifacts.MAX_LISTED_ARTIFACTS", 2)
        directory = task_artifacts_dir(CODE)
        for index in range(3):
            (directory / f"{index}.txt").write_text("x")

        assert len(list_artifacts(CODE)) == 2


class TestFileAndDelete:
    def test_missing_is_404(self) -> None:
        with pytest.raises(NotFoundError):
            artifact_file(CODE, "missing.txt")

    def test_delete(self) -> None:
        path = task_artifacts_dir(CODE) / "a.txt"
        path.write_text("x")

        delete_artifact(CODE, "a.txt")

        assert not path.exists()

    def test_delete_symlink_keeps_target(self) -> None:
        directory = task_artifacts_dir(CODE)
        (directory / "report.txt").write_text("report")
        (directory / "latest").symlink_to("report.txt")

        delete_artifact(CODE, "latest")

        assert not (directory / "latest").is_symlink()
        assert (directory / "report.txt").read_text() == "report"

    def test_delete_missing_is_404(self) -> None:
        with pytest.raises(NotFoundError):
            delete_artifact(CODE, "missing.txt")
