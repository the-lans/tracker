import pytest

from db.models.enums import UserRole
from services.knowledge_access import KnowledgeAccess, knowledge_access_for_role


@pytest.mark.parametrize("read,write", [(False, False), (True, False), (True, True)])
def test_roles_respect_section_access(read: bool, write: bool) -> None:
    access = KnowledgeAccess(read=read, write=write)
    assert knowledge_access_for_role(UserRole.USER, user_access=access) == access
    assert knowledge_access_for_role(UserRole.ADMIN, user_access=access) == KnowledgeAccess(
        read=True, write=True
    )


def test_write_requires_read() -> None:
    with pytest.raises(ValueError):
        KnowledgeAccess(read=False, write=True)
