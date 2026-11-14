"""
Файловое ядро публикации: не зависит от HTTP, сессий и запросов к БД.
"""

from __future__ import annotations

import errno
import os
import shutil
import uuid
from pathlib import Path

from services.knowledge_objects import KnowledgeProjection
from services.knowledge_storage import knowledge_object_path, validate_knowledge_path

_COPY_LINK_ERRORS = {errno.EXDEV, errno.EPERM, errno.ENOTSUP}


class KnowledgeProjectionPublisher:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _remove(path: Path) -> None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

    def _directory(self, path: Path) -> None:
        if path.is_dir():
            return
        if path.exists() or path.is_symlink():
            self._remove(path)
        if not path.parent.is_dir():
            self._directory(path.parent)
        path.mkdir(exist_ok=True)

    def _publish_file(self, source: Path, target: Path) -> None:
        self._directory(target.parent)
        if target.exists() and os.path.samestat(source.stat(), target.stat()):
            return
        if target.is_dir():
            self._remove(target)
        temporary = target.with_name(".tracker-" + uuid.uuid4().hex)
        try:
            try:
                os.link(source, temporary)
            except OSError as exc:
                if exc.errno not in _COPY_LINK_ERRORS:
                    raise
                shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _expected_paths(files: list[KnowledgeProjection]) -> set[str]:
        expected: set[str] = set()
        for item in files:
            validate_knowledge_path(item.path)
            parent = Path(item.path)
            expected.add(parent.as_posix())
            while parent.parent != Path("."):
                parent = parent.parent
                expected.add(parent.as_posix())
        return expected

    def _remove_obsolete(self, expected: set[str]) -> None:
        for path in sorted(self.root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.relative_to(self.root).as_posix() not in expected:
                self._remove(path)

    def publish(self, files: list[KnowledgeProjection]) -> None:
        expected = self._expected_paths(files)
        self._directory(self.root)
        for item in files:
            target = self.root / item.path
            if item.storage_key is None:
                self._directory(target)
            else:
                self._publish_file(knowledge_object_path(item.storage_key), target)
        self._remove_obsolete(expected)
