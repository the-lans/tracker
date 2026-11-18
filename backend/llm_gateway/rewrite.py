"""
Подстановка маршрута задачи в запрос сессии (раздел 19.7 ТЗ): любое значение
`model` от CLI заменяется на `<префикс>/<модель>` маршрута — в том числе у
служебных запросов к быстрой модели, — а запросу модели выставляется уровень
рассуждений в `output_config.effort`; прокси сам переводит его провайдеру.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple

from services.llm_routing import TurnRoute

MESSAGES_PATH = "/v1/messages"
COUNT_TOKENS_PATH = "/v1/messages/count_tokens"
MODELS_PATH = "/v1/models"
_OUTPUT_CONFIG_FIELD = "output_config"
_EFFORT_FIELD = "effort"
_MAX_TOKENS_FIELD = "max_tokens"
# Потолок выходных токенов: CLI считает `max_tokens` под модель, которую выбрал
# сам, а шлюз подменяет её на модель маршрута, и прокси отвечает 400 на запрос
# выше потолка этой модели. Для модели, которой нет в таблице, действует
# значение по умолчанию (не меньше 64 000); в таблице — модели с другим
# потолком. Ключ — часть имени модели маршрута, более длинные ключи — раньше
# коротких. Значения Anthropic — из документации, `opus-5-5` — по принятому
# прокси запросу.
DEFAULT_MAX_OUTPUT_TOKENS = 64_000
_MODEL_MAX_OUTPUT_TOKENS = {
    "claude-3-5-haiku": 8_192,
    "opus-4-1": 32_000,
    "opus-4-5": 64_000,
    "sonnet-4-5": 64_000,
    "haiku-4-5": 64_000,
    "opus-5-5": 128_000,
}


def _max_output_tokens(model: str) -> int:
    for marker, limit in _MODEL_MAX_OUTPUT_TOKENS.items():
        if marker in model:
            return limit
    return DEFAULT_MAX_OUTPUT_TOKENS


def _clamp_max_tokens(body: dict[str, Any], model: str) -> int | None:
    """Исходное `max_tokens`, если оно выше потолка модели и заменено; иначе None."""
    max_tokens = body.get(_MAX_TOKENS_FIELD)
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
        return None
    limit = _max_output_tokens(model)
    if max_tokens <= limit:
        return None
    body[_MAX_TOKENS_FIELD] = limit
    return max_tokens


class RewrittenBody(NamedTuple):
    content: bytes
    # Запрошенное сессией `max_tokens`, если шлюз снизил его до потолка модели.
    max_tokens_clamped_from: int | None = None


class InvalidRequestBodyError(ValueError):
    """Тело запроса сессии — не JSON-объект."""


def proxied_model(route: TurnRoute) -> str:
    return f"{route.prefix}/{route.model}"


def rewrite_body(path: str, raw: bytes, route: TurnRoute) -> RewrittenBody:
    try:
        body: Any = json.loads(raw)
    except ValueError as exc:
        raise InvalidRequestBodyError from exc
    if not isinstance(body, dict):
        raise InvalidRequestBodyError
    body["model"] = proxied_model(route)
    clamped_from = None
    if path == MESSAGES_PATH:
        clamped_from = _clamp_max_tokens(body, route.model)
        output_config = body.get(_OUTPUT_CONFIG_FIELD)
        if not isinstance(output_config, dict):
            output_config = {}
        output_config[_EFFORT_FIELD] = route.provider_effort.value
        body[_OUTPUT_CONFIG_FIELD] = output_config
    return RewrittenBody(json.dumps(body).encode(), clamped_from)
