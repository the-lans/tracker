"""Шлюз `llm-gateway` между сессией и LLM-прокси (раздел 19.7 ТЗ)."""

from __future__ import annotations

import gzip
import json
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import pytest_asyncio

from db.models.enums import ReasoningEffort
from llm_gateway.app import create_app, session_token
from llm_gateway.config import GatewayConfig
from services.llm_routing import TurnRoute, issue_session_token, publish_route

if TYPE_CHECKING:
    from redis.asyncio import Redis

_API_KEY = "proxy-client-key"
_ROUTE = TurnRoute(
    account_id=uuid.uuid4(),
    prefix="acc-0123456789ab",
    model="gpt-6-sol",
    effort=ReasoningEffort.MAX,
    provider_effort=ReasoningEffort.XHIGH,
)
_SSE = b"event: message_start\ndata: {}\n\nevent: message_stop\ndata: {}\n\n"


class Upstream:
    """Прокси: записывает пришедшие запросы и отвечает заданным ответом."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        # Ответ прокси: код, тело, заголовки — новый `httpx.Response` на каждый запрос.
        self.reply: tuple[int, bytes, dict[str, str]] = (
            200,
            _SSE,
            {"content-type": "text/event-stream"},
        )
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        self.requests.append(request)
        status_code, content, headers = self.reply
        return httpx.Response(status_code, content=content, headers=headers)

    def body(self) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[-1].content)
        return body


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest_asyncio.fixture
async def gateway(redis_client: Redis, upstream: Upstream) -> AsyncIterator[httpx.AsyncClient]:
    config = GatewayConfig(cliproxy_url="http://cliproxy:8317", cliproxy_api_key=_API_KEY)
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.handle)) as proxy_client:
        app = create_app(config=config, redis_client=redis_client, upstream=proxy_client)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
            yield client


@pytest_asyncio.fixture
async def token(redis_client: Redis) -> str:
    task_id = uuid.uuid4()
    await publish_route(redis_client, task_id, _ROUTE)
    return await issue_session_token(redis_client, task_id)


def _message(**fields: Any) -> dict[str, Any]:
    return {"model": "claude-haiku-5-5", "max_tokens": 16, "messages": [], **fields}


class TestSessionToken:
    @pytest.mark.parametrize(
        ("headers", "expected"),
        [
            ({"authorization": "Bearer tok"}, "tok"),
            ({"authorization": "bearer  tok "}, "tok"),
            ({"x-api-key": "tok"}, "tok"),
            ({"authorization": "Basic tok"}, None),
            ({}, None),
        ],
    )
    def test_extracted(self, headers: dict[str, str], expected: str | None) -> None:
        assert session_token(headers) == expected


class TestAuth:
    @pytest.mark.parametrize(
        "headers",
        [{}, {"authorization": "Bearer forged"}, {"x-api-key": "forged"}],
        ids=["missing", "bearer", "api_key"],
    )
    async def test_unknown_token_rejected(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        headers: dict[str, str],
    ) -> None:
        response = await gateway.post("/v1/messages", json=_message(), headers=headers)

        assert response.status_code == 401
        assert response.json()["error"]["type"] == "authentication_error"
        assert upstream.requests == []

    async def test_task_without_route(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        redis_client: Redis,
    ) -> None:
        token = await issue_session_token(redis_client, uuid.uuid4())

        response = await gateway.post("/v1/messages", json=_message(), headers={"x-api-key": token})

        assert response.status_code == 503
        assert upstream.requests == []

    async def test_head_answered_locally(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
    ) -> None:
        response = await gateway.head("/")

        assert (response.status_code, upstream.requests) == (200, [])

    async def test_health(self, gateway: httpx.AsyncClient) -> None:
        assert (await gateway.get("/health")).json() == {"status": "ok"}


class TestRewrite:
    async def test_model_and_effort(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
    ) -> None:
        payload = _message(output_config={"effort": "low", "format": {"type": "text"}}, stream=True)

        response = await gateway.post(
            "/v1/messages",
            json=payload,
            headers={"authorization": f"Bearer {token}"},
        )

        assert (response.status_code, response.content) == (200, _SSE)
        assert response.headers["content-type"] == "text/event-stream"
        sent = upstream.body()
        assert sent["model"] == "acc-0123456789ab/gpt-6-sol"
        assert sent["output_config"] == {"effort": "xhigh", "format": {"type": "text"}}
        assert sent["stream"] is True

    async def test_count_tokens_without_effort(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
    ) -> None:
        await gateway.post(
            "/v1/messages/count_tokens",
            json={"model": "claude-opus-5-5", "messages": []},
            headers={"x-api-key": token},
        )

        assert upstream.body() == {"model": "acc-0123456789ab/gpt-6-sol", "messages": []}

    async def test_headers_to_proxy(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
    ) -> None:
        await gateway.post(
            "/v1/messages?beta=true",
            json=_message(),
            headers={
                "x-api-key": token,
                "anthropic-beta": "oauth-2025-04-20",
                "accept-encoding": "gzip, zstd",
            },
        )

        sent = upstream.requests[-1]
        assert str(sent.url) == "http://cliproxy:8317/v1/messages?beta=true"
        assert sent.headers["authorization"] == f"Bearer {_API_KEY}"
        assert "x-api-key" not in sent.headers
        assert token not in str(sent.headers)
        assert sent.headers["accept-encoding"] == "identity"
        assert sent.headers["anthropic-beta"] == "oauth-2025-04-20"

    async def test_models_list_passed(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
    ) -> None:
        upstream.reply = (200, b'{"data": []}', {"content-type": "application/json"})

        response = await gateway.get("/v1/models", headers={"x-api-key": token})

        assert (response.status_code, response.json()) == (200, {"data": []})
        assert (upstream.requests[-1].method, upstream.requests[-1].content) == ("GET", b"")

    @pytest.mark.parametrize("content", [b"not json", b"[1]"])
    async def test_invalid_body(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
        content: bytes,
    ) -> None:
        response = await gateway.post("/v1/messages", content=content, headers={"x-api-key": token})

        assert (response.status_code, upstream.requests) == (400, [])


class TestUpstream:
    async def test_error_passed_unchanged(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
    ) -> None:
        error = {"type": "error", "error": {"type": "rate_limit_error", "message": "limit"}}
        upstream.reply = (429, json.dumps(error).encode(), {"retry-after": "30"})

        response = await gateway.post("/v1/messages", json=_message(), headers={"x-api-key": token})

        assert (response.status_code, response.json()) == (429, error)
        assert response.headers["retry-after"] == "30"

    async def test_compressed_reply_decoded(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
    ) -> None:
        upstream.reply = (200, gzip.compress(_SSE), {"content-encoding": "gzip"})

        response = await gateway.post("/v1/messages", json=_message(), headers={"x-api-key": token})

        assert response.content == _SSE
        assert "content-encoding" not in response.headers

    async def test_proxy_down(
        self,
        gateway: httpx.AsyncClient,
        upstream: Upstream,
        token: str,
    ) -> None:
        upstream.down = True

        response = await gateway.post("/v1/messages", json=_message(), headers={"x-api-key": token})

        assert response.status_code == 502
        assert response.json()["error"]["type"] == "api_error"
