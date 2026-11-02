"""Настройки шлюза `llm-gateway` (разделы 19.7, 20.3 ТЗ)."""

from __future__ import annotations

import os
from dataclasses import dataclass

LOGGER_NAME = "llm_gateway"
DEFAULT_PORT = 8320
DEFAULT_CLIPROXY_URL = "http://cliproxy:8317"
_PORT_ENV = "LLM_GATEWAY_PORT"
_CLIPROXY_URL_ENV = "CLIPROXY_URL"
_CLIPROXY_API_KEY_ENV = "CLIPROXY_API_KEY"


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    cliproxy_url: str
    # Ключ клиентского API прокси (`access.api-keys`) — сессии он не выдаётся.
    cliproxy_api_key: str
    port: int = DEFAULT_PORT


def load_config() -> GatewayConfig:
    """Без ключа прокси шлюз не стартует: запросы сессий всё равно отклонялись бы."""
    return GatewayConfig(
        cliproxy_url=os.environ.get(_CLIPROXY_URL_ENV, DEFAULT_CLIPROXY_URL).rstrip("/"),
        cliproxy_api_key=os.environ[_CLIPROXY_API_KEY_ENV],
        port=int(os.environ.get(_PORT_ENV, DEFAULT_PORT)),
    )
