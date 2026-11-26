"""Cookie браузера и фиксированный Origin пользовательского API."""

import os

from fastapi import Response

from services.auth_tokens import DEFAULT_SESSION_TTL

CSRF_HEADER = "X-Tracker-Request"
CSRF_HEADER_VALUE = "1"
UNSAFE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PUBLIC_ORIGIN_ENV = "TRACKER_PUBLIC_ORIGIN"
_DEFAULT_PUBLIC_ORIGIN = "https://tracker.botelo.ru"
_DEV_COOKIE_ENV = "TRACKER_DEV_COOKIE"
_PRODUCTION_COOKIE = "__Host-tracker_session"
_DEV_COOKIE = "tracker_dev_session"


def public_origin() -> str:
    return os.environ.get(_PUBLIC_ORIGIN_ENV, _DEFAULT_PUBLIC_ORIGIN)


def dev_cookie() -> bool:
    return os.environ.get(_DEV_COOKIE_ENV, "false").lower() == "true"


def session_cookie_name() -> str:
    return _DEV_COOKIE if dev_cookie() else _PRODUCTION_COOKIE


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        session_cookie_name(),
        token,
        max_age=int(DEFAULT_SESSION_TTL.total_seconds()),
        httponly=True,
        secure=not dev_cookie(),
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        session_cookie_name(),
        path="/",
        secure=not dev_cookie(),
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
