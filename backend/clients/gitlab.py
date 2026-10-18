"""Обёртка над GitLab REST API v4 (раздел 16.2 ТЗ).

Решение №5 плана реализации: токен GitLab API — один общий на систему,
берётся из `env_variables` (`scope = global`), не отдельное поле в
`repositories` — этот клиент принимает уже готовый токен, ответственность
за его выбор — у вызывающего кода.
"""

from __future__ import annotations

from typing import Any

import httpx

from app_logging.config import get_logger
from services.errors import ExternalServiceError

logger = get_logger("gitlab_client")

_API_BASE_PATH = "/api/v4"
_SERVER_ERROR_THRESHOLD = 500
_CLIENT_ERROR_THRESHOLD = 400


def project_path_from_git_url(git_url: str) -> str:
    """`git@gitlab.com:group/project.git` или `https://gitlab.com/group/project.git`.

    Оба варианта -> `group/project`.
    """
    cleaned = git_url.removesuffix(".git")
    if "://" in cleaned:
        _, _, remainder = cleaned.partition("://")
        _, _, path = remainder.partition("/")
        return path
    _, _, path = cleaned.partition(":")
    return path


class GitlabClient:
    def __init__(self, *, base_url: str, token: str, http_client: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._http_client = http_client

    async def _get(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        url = f"{self._base_url}{_API_BASE_PATH}{path}"
        try:
            response = await self._http_client.get(
                url,
                params=params,
                headers={"PRIVATE-TOKEN": self._token},
            )
        except httpx.TransportError as exc:
            message = f"Сетевая ошибка обращения к GitLab: {exc}"
            raise ExternalServiceError(message, is_transient=True) from exc

        if response.status_code >= _SERVER_ERROR_THRESHOLD:
            message = f"GitLab вернул {response.status_code} для {path}"
            raise ExternalServiceError(message, is_transient=True)
        if response.status_code >= _CLIENT_ERROR_THRESHOLD:
            message = f"GitLab вернул {response.status_code} для {path}: {response.text}"
            raise ExternalServiceError(message, is_transient=False)
        return response.json()

    async def get_latest_merge_request_state(
        self,
        *,
        project_path: str,
        source_branch: str,
    ) -> str | None:
        """Состояние (`opened`/`closed`/`merged`) самого свежего MR для ветки, либо `None`."""
        encoded_path = project_path.replace("/", "%2F")
        merge_requests = await self._get(
            f"/projects/{encoded_path}/merge_requests",
            params={"source_branch": source_branch, "order_by": "updated_at", "sort": "desc"},
        )
        if not merge_requests:
            return None
        return str(merge_requests[0]["state"])
