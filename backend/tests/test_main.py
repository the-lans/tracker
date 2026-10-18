from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.errors import NotFoundError


def test_health_endpoint() -> None:
    from main import app

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_error_handler_returns_standard_shape() -> None:
    from main import app, app_error_handler

    probe = FastAPI()
    probe.exception_handler(NotFoundError)(app_error_handler)

    @probe.get("/boom")
    async def boom() -> None:
        raise NotFoundError("задача не найдена")

    with TestClient(probe, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "задача не найдена"
    assert "request_id" in body["error"]
    assert app is not None  # смок: модуль main импортируется без побочных ошибок


def test_unhandled_exception_returns_500_without_leaking_details() -> None:
    from main import unhandled_exception_handler

    probe = FastAPI()
    probe.exception_handler(Exception)(unhandled_exception_handler)

    @probe.get("/crash")
    async def crash() -> None:
        raise RuntimeError("детали внутренней реализации")

    with TestClient(probe, raise_server_exceptions=False) as client:
        response = client.get("/crash")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "детали внутренней реализации" not in body["error"]["message"]
    assert "request_id" in body["error"]
