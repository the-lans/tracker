"""
Признак «загружен с диска» у файлов шаблона (`templates.uploaded_file_paths`,
разделы 3.1, 15.1 ТЗ).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable


def resolve_uploaded_file_paths(
    files: Collection[str],
    uploaded: Iterable[str] | None,
    *,
    previous: Iterable[str] = (),
) -> list[str]:
    """
    Пути файлов шаблона, загруженных с диска, после сохранения. ``uploaded``
    не передан — остаются прежние пути, кроме удалённых из ``files``; путь,
    которого нет в ``files``, — ошибка.
    """
    if uploaded is None:
        return [path for path in previous if path in files]
    paths = list(dict.fromkeys(uploaded))
    unknown = [path for path in paths if path not in files]
    if unknown:
        raise ValidationError(
            f"Файла {unknown[0]} нет в шаблоне — он не может быть отмечен как загруженный с диска",
        )
    return paths
