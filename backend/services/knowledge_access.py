"""
Правила доступа к разделам базы знаний.

Права пользователя применяются также к агенту задачи; настройки агента
фиксируются при старте сессии.
"""

from db.models.enums import UserRole
from services.knowledge_objects import KnowledgeAccess as KnowledgeAccess


def knowledge_access_for_role(role: UserRole, *, user_access: KnowledgeAccess) -> KnowledgeAccess:
    if role is UserRole.ADMIN:
        return KnowledgeAccess(read=True, write=True)
    return user_access
