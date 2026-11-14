"""
Правила доступа к разделам базы знаний.

Права пользователя применяются также к агенту задачи; настройки агента
фиксируются при старте сессии.
"""

from dataclasses import dataclass

from db.models.enums import UserRole


@dataclass(frozen=True, slots=True)
class KnowledgeAccess:
    read: bool
    write: bool

    def __post_init__(self) -> None:
        if self.write and not self.read:
            raise ValueError("Право записи требует права чтения")


def knowledge_access_for_role(role: UserRole, *, user_access: KnowledgeAccess) -> KnowledgeAccess:
    if role is UserRole.ADMIN:
        return KnowledgeAccess(read=True, write=True)
    return user_access
