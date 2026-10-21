"""
`/llm-accounts` (раздел 3.1, 19.2, 19.5 ТЗ, решение №17 плана): аккаунт
личный — `user` видит и меняет только свои, `admin` — все; путь
конфигурационной директории уникален; аккаунт задачи — только её автора.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from db.models.enums import TaskStatus
from db.models.tasks import Task
from services.llm_accounts import DEFAULT_ACCOUNTS_ROOT
from tests.factories import make_llm_account, make_user

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from db.models.users import User


async def _task(db_session: AsyncSession, owner_id: uuid.UUID, **fields: Any) -> Task:
    task = Task(
        code=f"RR-{uuid.uuid4().hex[:6]}",
        title="t",
        description="d",
        created_by=owner_id,
        status=fields.pop("status", TaskStatus.NEW),
        **fields,
    )
    db_session.add(task)
    await db_session.flush()
    return task


_ROOT = DEFAULT_ACCOUNTS_ROOT


class TestCreate:
    async def test_owner_is_current_user(
        self,
        authed_client: AsyncClient,
        current_user: User,
    ) -> None:
        response = await authed_client.post(
            "/llm-accounts",
            json={"label": "личный", "claude_config_dir": f"{_ROOT}//dev/"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["created_by"] == str(current_user.id)
        assert response.json()["claude_config_dir"] == f"{_ROOT}/dev"

    @pytest.mark.parametrize(
        "variant",
        ["svc", "svc/", "/svc", "./svc", "svc/nested", "svc/../svc"],
        ids=["same", "trailing_slash", "double_slash", "dot", "nested", "dotdot"],
    )
    async def test_overlaps_other_account(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        variant: str,
    ) -> None:
        """Раздел 19.5: чужой каталог не занять другим написанием пути."""
        other = await make_user(db_session)
        await make_llm_account(db_session, owner_id=other.id, claude_config_dir=f"{_ROOT}/svc")

        response = await authed_client.post(
            "/llm-accounts",
            json={"label": "копия", "claude_config_dir": f"{_ROOT}/{variant}"},
        )

        assert response.status_code == 409

    async def test_parent_of_other_account(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        await make_llm_account(db_session, owner_id=other.id, claude_config_dir=f"{_ROOT}/team/a")

        response = await authed_client.post(
            "/llm-accounts",
            json={"label": "родитель", "claude_config_dir": f"{_ROOT}/team"},
        )

        assert response.status_code == 409

    @pytest.mark.parametrize(
        "path",
        ["/home/svc/.claude", _ROOT, f"{_ROOT}/../etc", "relative/.claude"],
        ids=["outside", "root_itself", "escape", "relative"],
    )
    async def test_outside_root(self, authed_client: AsyncClient, path: str) -> None:
        response = await authed_client.post(
            "/llm-accounts",
            json={"label": "вне корня", "claude_config_dir": path},
        )

        assert response.status_code == 422


class TestList:
    async def test_user_sees_only_own(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        own = await make_llm_account(db_session, owner_id=current_user.id)
        foreign = await make_llm_account(db_session, owner_id=other.id)

        ids = {item["id"] for item in (await authed_client.get("/llm-accounts")).json()}

        assert str(own.id) in ids
        assert str(foreign.id) not in ids

    async def test_admin_sees_all(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)

        ids = {item["id"] for item in (await admin_client.get("/llm-accounts")).json()}

        assert str(foreign.id) in ids


class TestForeignAccount:
    @pytest.mark.parametrize(
        ("method", "payload"),
        [("get", None), ("patch", {"label": "чужой"}), ("delete", None)],
        ids=["get", "patch", "delete"],
    )
    async def test_is_404(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
        method: str,
        payload: dict[str, str] | None,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)
        kwargs = {"json": payload} if payload is not None else {}

        response = await getattr(authed_client, method)(f"/llm-accounts/{foreign.id}", **kwargs)

        assert response.status_code == 404

    async def test_admin_changes_foreign(
        self,
        admin_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)

        response = await admin_client.patch(f"/llm-accounts/{foreign.id}", json={"label": "новое"})

        assert response.status_code == 200
        assert response.json()["label"] == "новое"


class TestUpdate:
    async def test_config_dir_taken(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)
        other = await make_llm_account(db_session, owner_id=current_user.id)

        response = await authed_client.patch(
            f"/llm-accounts/{account.id}",
            json={"claude_config_dir": other.claude_config_dir},
        )

        assert response.status_code == 409

    async def test_same_config_dir_kept(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)

        response = await authed_client.patch(
            f"/llm-accounts/{account.id}",
            json={"claude_config_dir": account.claude_config_dir, "label": "переименован"},
        )

        assert response.status_code == 200


class TestDelete:
    async def test_unused(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)

        response = await authed_client.delete(f"/llm-accounts/{account.id}")

        assert response.status_code == 204

    async def test_used_by_task(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        account = await make_llm_account(db_session, owner_id=current_user.id)
        await _task(db_session, current_user.id, llm_account_id=account.id)

        response = await authed_client.delete(f"/llm-accounts/{account.id}")

        assert response.status_code == 409


class TestTaskAccount:
    """Раздел 19.2: LLM-аккаунт задачи — только один из аккаунтов её автора."""

    async def test_create_with_foreign_account(
        self,
        authed_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)

        response = await authed_client.post(
            "/tasks",
            json={
                "code": "RR-20001",
                "title": "t",
                "description": "d",
                "llm_account_id": str(foreign.id),
            },
        )

        assert response.status_code == 404

    async def test_admin_sets_own_account_on_foreign_task(
        self,
        admin_client: AsyncClient,
        admin_user: User,
        db_session: AsyncSession,
    ) -> None:
        author = await make_user(db_session)
        task = await _task(db_session, author.id)
        admin_account = await make_llm_account(db_session, owner_id=admin_user.id)
        author_account = await make_llm_account(db_session, owner_id=author.id)

        rejected = await admin_client.patch(
            f"/tasks/{task.id}",
            json={"llm_account_id": str(admin_account.id)},
        )
        accepted = await admin_client.patch(
            f"/tasks/{task.id}",
            json={"llm_account_id": str(author_account.id)},
        )

        assert rejected.status_code == 404
        assert accepted.status_code == 200

    async def test_duplicate_with_foreign_account(
        self,
        authed_client: AsyncClient,
        current_user: User,
        db_session: AsyncSession,
    ) -> None:
        other = await make_user(db_session)
        foreign = await make_llm_account(db_session, owner_id=other.id)
        source = await _task(db_session, current_user.id, status=TaskStatus.DONE)

        response = await authed_client.post(
            f"/tasks/{source.id}/duplicate",
            json={
                "code": "RR-20002",
                "title": "t",
                "description": "d",
                "llm_account_id": str(foreign.id),
            },
        )

        assert response.status_code == 404
