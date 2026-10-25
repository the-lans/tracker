"""
Классы неуспешных HTTP-ответов внешних API (GitLab, Jira) — раздел 17.3 ТЗ:
временный сбой повторяется, отказ в доступе и прочие 4xx — нет.
"""

from __future__ import annotations

from enum import Enum

import httpx

_SERVER_ERROR_THRESHOLD = 500
_CLIENT_ERROR_THRESHOLD = 400
# Таймаут запроса и упор в лимит — временные, хотя это 4xx.
_TRANSIENT_CLIENT_STATUSES = frozenset({httpx.codes.REQUEST_TIMEOUT, httpx.codes.TOO_MANY_REQUESTS})
_ACCESS_DENIED_STATUSES = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


class HttpFailure(Enum):
    TRANSIENT = "transient"
    ACCESS_DENIED = "access_denied"
    CLIENT_ERROR = "client_error"


def classify_status(status: int) -> HttpFailure | None:
    """Класс сбоя по коду ответа; успешный ответ — ``None``."""
    if status >= _SERVER_ERROR_THRESHOLD or status in _TRANSIENT_CLIENT_STATUSES:
        return HttpFailure.TRANSIENT
    if status in _ACCESS_DENIED_STATUSES:
        return HttpFailure.ACCESS_DENIED
    if status >= _CLIENT_ERROR_THRESHOLD:
        return HttpFailure.CLIENT_ERROR
    return None
