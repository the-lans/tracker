"""
ASGI-приложение шлюза `llm-gateway` (раздел 19.7 ТЗ).

Запрос сессии: токен из `Authorization: Bearer` или `x-api-key` → задача
(неизвестный токен — 401 без обращения к прокси) → маршрут задачи →
подмена `model` и уровня рассуждений → прокси с ключом клиентского API.
Ответ прокси запрашивается несжатым и передаётся потоком без изменений.
Проверку адреса `HEAD` от CLI шлюз подтверждает сам.

В прокси уходят только ход и подсчёт токенов (`MESSAGES_PATH`,
`COUNT_TOKENS_PATH`): у других эндпоинтов прокси модель бывает в адресе, и
подмена `model` в теле не удержала бы сессию на учётке её маршрута. Список
моделей шлюз отдаёт сам — только модель маршрута, без префиксов чужих учёток.
Остальные пути — 404 без обращения к прокси.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from app_logging.config import get_logger
from llm_gateway.config import LOGGER_NAME, GatewayConfig
from llm_gateway.rewrite import (
    COUNT_TOKENS_PATH,
    MESSAGES_PATH,
    MODELS_PATH,
    InvalidRequestBodyError,
    rewrite_body,
)
from services.llm_routing import TurnRoute, read_route, resolve_session_token

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(LOGGER_NAME)

_BEARER = "bearer "
# Ключ сессии и транспортные заголовки клиента прокси не уходят.
_DROPPED_REQUEST_HEADERS = frozenset(
    {
        "host",
        "authorization",
        "x-api-key",
        "content-length",
        "accept-encoding",
        "connection",
        "transfer-encoding",
    },
)
_DROPPED_RESPONSE_HEADERS = frozenset(
    {"content-length", "content-encoding", "transfer-encoding", "connection"},
)
_IDENTITY_ENCODING = "identity"
# Методы, которыми шлюз отвечает 404 на пути вне белого списка.
_REJECTED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _error(status_code: int, error_type: str, message: str) -> JSONResponse:
    """Ошибка в формате Anthropic API — CLI показывает её как ответ модели."""
    payload = {"type": "error", "error": {"type": error_type, "message": message}}
    return JSONResponse(payload, status_code=status_code)


def session_token(headers: Mapping[str, str]) -> str | None:
    authorization = headers.get("authorization", "")
    if authorization.lower().startswith(_BEARER):
        return authorization[len(_BEARER) :].strip() or None
    return headers.get("x-api-key") or None


def _upstream_headers(headers: Mapping[str, str], api_key: str) -> dict[str, str]:
    forwarded = {
        name: value
        for name, value in headers.items()
        if name.lower() not in _DROPPED_REQUEST_HEADERS
    }
    forwarded["accept-encoding"] = _IDENTITY_ENCODING
    forwarded["authorization"] = f"Bearer {api_key}"
    return forwarded


def _response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in _DROPPED_RESPONSE_HEADERS
    }


def _models_list(route: TurnRoute) -> dict[str, object]:
    """Список моделей в формате Anthropic API: только модель маршрута задачи."""
    model = {"type": "model", "id": route.model, "display_name": route.model}
    return {"data": [model], "has_more": False, "first_id": route.model, "last_id": route.model}


class LlmGateway:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        redis_client: Redis,
        upstream: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._redis = redis_client
        self._upstream = upstream

    async def _route(self, request: Request) -> tuple[uuid.UUID, TurnRoute] | Response:
        token = session_token(request.headers)
        task_id = await resolve_session_token(self._redis, token) if token else None
        if task_id is None:
            return _error(401, "authentication_error", "Неизвестный токен сессии")
        route = await read_route(self._redis, task_id)
        if route is None:
            logger.warning("llm_gateway_no_route", task_id=str(task_id), path=request.url.path)
            return _error(503, "api_error", "Для задачи не выбран LLM-аккаунт")
        return task_id, route

    async def models(self, request: Request) -> Response:
        resolved = await self._route(request)
        if isinstance(resolved, Response):
            return resolved
        return JSONResponse(_models_list(resolved[1]))

    async def messages(self, request: Request) -> Response:
        resolved = await self._route(request)
        if isinstance(resolved, Response):
            return resolved
        task_id, route = resolved
        content = await request.body()
        if content:
            try:
                content = rewrite_body(request.url.path, content, route)
            except InvalidRequestBodyError:
                return _error(400, "invalid_request_error", "Тело запроса — не JSON-объект")
        return await self._forward(request, task_id=task_id, content=content)

    async def _forward(self, request: Request, *, task_id: uuid.UUID, content: bytes) -> Response:
        upstream_request = self._upstream.build_request(
            request.method,
            f"{self._config.cliproxy_url}{request.url.path}",
            params=request.query_params,
            headers=_upstream_headers(request.headers, self._config.cliproxy_api_key),
            content=content,
        )
        try:
            upstream_response = await self._upstream.send(upstream_request, stream=True)
        except httpx.TransportError as exc:
            logger.warning(
                "llm_gateway_upstream_unavailable",
                task_id=str(task_id),
                error=type(exc).__name__,
            )
            return _error(502, "api_error", "LLM-прокси недоступен")
        logger.info(
            "llm_gateway_request",
            task_id=str(task_id),
            path=request.url.path,
            status_code=upstream_response.status_code,
        )
        # `aiter_bytes`: если прокси всё же сжал ответ, сессия получит его распакованным
        # (заголовок `content-encoding` не пересылается).
        return StreamingResponse(
            upstream_response.aiter_bytes(),
            status_code=upstream_response.status_code,
            headers=_response_headers(upstream_response.headers),
            background=BackgroundTask(upstream_response.aclose),
        )


async def _health(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def _address_check(_: Request) -> Response:
    return Response(status_code=200)


async def _not_found(request: Request) -> Response:
    logger.warning("llm_gateway_path_rejected", method=request.method, path=request.url.path)
    return _error(404, "not_found_error", "Шлюз не пропускает этот запрос")


def create_app(
    *,
    config: GatewayConfig,
    redis_client: Redis,
    upstream: httpx.AsyncClient,
) -> Starlette:
    gateway = LlmGateway(config=config, redis_client=redis_client, upstream=upstream)
    return Starlette(
        routes=[
            Route("/health", _health, methods=["GET"]),
            Route(MESSAGES_PATH, gateway.messages, methods=["POST"]),
            Route(COUNT_TOKENS_PATH, gateway.messages, methods=["POST"]),
            Route(MODELS_PATH, gateway.models, methods=["GET"]),
            Route("/{path:path}", _address_check, methods=["HEAD"]),
            Route("/{path:path}", _not_found, methods=_REJECTED_METHODS),
        ],
    )
