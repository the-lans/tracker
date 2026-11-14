"""
Неизменяемые объекты прикладного слоя базы знаний.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeAccess:
    read: bool
    write: bool

    def __post_init__(self) -> None:
        if self.write and not self.read:
            raise ValueError("Право записи требует права чтения")


@dataclass(frozen=True, slots=True)
class KnowledgeSectionSnapshot:
    id: uuid.UUID
    name: str
    user_read: bool
    user_write: bool


@dataclass(frozen=True, slots=True)
class KnowledgeProjection:
    path: str
    storage_key: str | None
