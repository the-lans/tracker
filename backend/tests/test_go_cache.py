"""Кеши Go сессии задачи: каталог в томе сессий, порог между нодами, удаление при done."""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

from services.go_cache import (
    BUILD_CACHE_DIRNAME,
    MODULE_CACHE_DIRNAME,
    directory_size,
    go_cache_env,
    remove_go_cache,
    trim_go_cache,
)

if TYPE_CHECKING:
    from pathlib import Path

LIMIT = 1000
CODE = "RR-1"


@pytest.fixture
def task_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_SESSIONS_ROOT", str(tmp_path))
    directory = tmp_path / CODE
    directory.mkdir()
    return directory


def _fill(directory: Path, name: str, size: int) -> Path:
    cache = directory / name
    (cache / "ab").mkdir(parents=True)
    (cache / "ab" / "entry").write_bytes(b"x" * size)
    return cache


class TestEnv:
    def test_caches_inside_task_directory(self, tmp_path: Path) -> None:
        assert go_cache_env(tmp_path / CODE) == {
            "GOCACHE": f"{tmp_path}/{CODE}/{BUILD_CACHE_DIRNAME}",
            "GOMODCACHE": f"{tmp_path}/{CODE}/{MODULE_CACHE_DIRNAME}",
        }


class TestDirectorySize:
    def test_sums_nested_files(self, task_dir: Path) -> None:
        _fill(task_dir, "go-cache", 300)
        (task_dir / "go-cache" / "top").write_bytes(b"y" * 50)

        assert directory_size(task_dir / "go-cache") == 350

    def test_missing_directory_is_empty(self, task_dir: Path) -> None:
        assert directory_size(task_dir / "absent") == 0


class TestTrim:
    @pytest.mark.parametrize(
        ("build", "modules", "build_left", "modules_left"),
        [
            (400, 400, True, True),
            (LIMIT, 0, True, True),
            (700, 400, False, True),
            (200, 1200, False, False),
        ],
        ids=["within_limit", "exactly_limit", "build_over", "modules_alone_over"],
    )
    async def test_by_threshold(
        self,
        task_dir: Path,
        build: int,
        modules: int,
        build_left: bool,
        modules_left: bool,
    ) -> None:
        build_dir = _fill(task_dir, BUILD_CACHE_DIRNAME, build)
        modules_dir = _fill(task_dir, MODULE_CACHE_DIRNAME, modules)

        freed = await trim_go_cache(CODE, limit=LIMIT)

        assert (build_dir.exists(), modules_dir.exists()) == (build_left, modules_left)
        assert (freed > 0) == (not build_left)

    async def test_without_caches(self, task_dir: Path) -> None:
        assert await trim_go_cache(CODE, limit=LIMIT) == 0

    async def test_read_only_modules(self, task_dir: Path) -> None:
        """Кеш модулей Go — каталоги и файлы только для чтения: удаляется всё равно."""
        modules = _fill(task_dir, MODULE_CACHE_DIRNAME, 2 * LIMIT)
        os.chmod(modules / "ab" / "entry", stat.S_IRUSR)
        os.chmod(modules / "ab", stat.S_IRUSR | stat.S_IXUSR)

        await trim_go_cache(CODE, limit=LIMIT)

        assert not modules.exists()


class TestRemove:
    async def test_removes_both_caches_only(self, task_dir: Path) -> None:
        _fill(task_dir, BUILD_CACHE_DIRNAME, 10)
        _fill(task_dir, MODULE_CACHE_DIRNAME, 10)
        (task_dir / "settings.json").write_text("{}")

        await remove_go_cache(CODE)

        assert sorted(path.name for path in task_dir.iterdir()) == ["settings.json"]

    async def test_without_caches(self, task_dir: Path) -> None:
        await remove_go_cache(CODE)

        assert list(task_dir.iterdir()) == []
