"""
Подстановка маршрута задачи в запрос сессии (раздел 19.7 ТЗ): любое значение
`model` от CLI заменяется на `<префикс>/<модель>` маршрута — в том числе у
служебных запросов к быстрой модели, — а запросу модели выставляется уровень
рассуждений в `output_config.effort`; прокси сам переводит его провайдеру.
"""

from __future__ import annotations

import json
from typing import Any

from services.llm_routing import TurnRoute

MESSAGES_PATH = "/v1/messages"
_OUTPUT_CONFIG_FIELD = "output_config"
_EFFORT_FIELD = "effort"


class InvalidRequestBodyError(ValueError):
    """Тело запроса сессии — не JSON-объект."""


def proxied_model(route: TurnRoute) -> str:
    return f"{route.prefix}/{route.model}"


def rewrite_body(path: str, raw: bytes, route: TurnRoute) -> bytes:
    try:
        body: Any = json.loads(raw)
    except ValueError as exc:
        raise InvalidRequestBodyError from exc
    if not isinstance(body, dict):
        raise InvalidRequestBodyError
    body["model"] = proxied_model(route)
    if path == MESSAGES_PATH:
        output_config = body.get(_OUTPUT_CONFIG_FIELD)
        if not isinstance(output_config, dict):
            output_config = {}
        output_config[_EFFORT_FIELD] = route.provider_effort.value
        body[_OUTPUT_CONFIG_FIELD] = output_config
    return json.dumps(body).encode()
