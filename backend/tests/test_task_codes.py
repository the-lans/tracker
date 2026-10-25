"""
Код задачи (раздел 3.1 ТЗ): любой текст без пробелов, но код — ещё и каталог
задачи и часть рабочей ветки, поэтому путь наружу и недопустимое имя ветки
отклоняются.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from services.errors import ValidationError
from services.task_codes import MAX_TASK_CODE_LENGTH, validate_task_code

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestValidateTaskCode:
    @pytest.mark.parametrize(
        "code",
        ["RR-12345", "PROJ-7", "задача_1", "fix.login", "A" * MAX_TASK_CODE_LENGTH],
    )
    def test_accepted(self, code: str) -> None:
        assert validate_task_code(code) == code

    @pytest.mark.parametrize(
        "code",
        [
            "",
            "RR 1",
            "RR\t1",
            "x/../RR-1",
            "a/b",
            "a\\b",
            ".",
            "..",
            "a..b",
            "-rf",
            ".hidden",
            "name.",
            "name.lock",
            "a~1",
            "a^1",
            "a:1",
            "a?1",
            "a*1",
            "a[1",
            "a@{1",
            "a\x00b",
            "A" * (MAX_TASK_CODE_LENGTH + 1),
        ],
    )
    def test_rejected(self, code: str) -> None:
        with pytest.raises(ValidationError):
            validate_task_code(code)


class TestCreateTaskCode:
    @pytest.mark.parametrize("code", ["x/../RR-77777", ".", "RR 1"])
    async def test_rejected_by_api(self, authed_client: AsyncClient, code: str) -> None:
        response = await authed_client.post(
            "/tasks",
            json={"code": code, "title": "t", "description": "d"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_any_text_without_spaces_accepted(self, authed_client: AsyncClient) -> None:
        response = await authed_client.post(
            "/tasks",
            json={"code": "PROJ-42", "title": "t", "description": "d"},
        )
        assert response.status_code == 201
