import asyncio
import time

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app_logging import app_logs
from db.models.logs import AppLog
from db.session import async_session_factory
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


def test_unhandled_exception_returns_500_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main
    from main import unhandled_exception_handler

    async def skip_write(**_kwargs: object) -> None:
        return None

    # TestClient крутит свой цикл событий — запись в БД проверяет TestUnhandledErrorLog.
    monkeypatch.setattr(main, "write_app_log", skip_write)

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


def _crashing_app() -> FastAPI:
    from main import unhandled_exception_handler

    probe = FastAPI()
    probe.exception_handler(Exception)(unhandled_exception_handler)

    @probe.get("/crash")
    async def crash() -> None:
        raise RuntimeError("сломалось")

    return probe


async def _crash() -> str:
    transport = ASGITransport(app=_crashing_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/crash")
    assert response.status_code == 500
    request_id: str = response.json()["error"]["request_id"]
    return request_id


class TestUnhandledErrorLog:
    """Раздел 17.2, 17.3: ответ 500 оставляет запись `app_logs` с тем же `request_id`."""

    async def test_written(self, run_migrations: None) -> None:
        request_id = await _crash()

        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(AppLog).where(AppLog.context["request_id"].astext == request_id),
                )
            ).scalars().all()
            await session.execute(sa.delete(AppLog).where(AppLog.id.in_([r.id for r in rows])))
            await session.commit()

        assert len(rows) == 1
        assert rows[0].source == "api"
        assert rows[0].context["path"] == "/crash"
        assert "RuntimeError" in rows[0].context["traceback"]

    @pytest.mark.parametrize(
        "error",
        [ConnectionRefusedError("БД недоступна"), SQLAlchemyError("ошибка записи")],
        ids=["db_unreachable", "db_error"],
    )
    async def test_write_failure_keeps_standard_500(
        self,
        monkeypatch: pytest.MonkeyPatch,
        error: Exception,
    ) -> None:
        async def refused(_app_log: AppLog) -> None:
            raise error

        monkeypatch.setattr(app_logs, "_insert", refused)

        assert await _crash()

    async def test_slow_db_does_not_delay_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def hang(_app_log: AppLog) -> None:
            await asyncio.sleep(30)

        monkeypatch.setattr(app_logs, "_insert", hang)
        monkeypatch.setattr(app_logs, "WRITE_TIMEOUT_SECONDS", 0.05)

        started = time.monotonic()
        assert await _crash()
        assert time.monotonic() - started < 5
