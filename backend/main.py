"""FastAPI app factory (раздел 2.3, 2.4, 17.3 ТЗ)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from api.auth import router as auth_router
from api.env_variables import router as env_variables_router
from api.llm_accounts import router as llm_accounts_router
from api.mcp_servers import router as mcp_servers_router
from api.monitoring import monitoring_router
from api.monitoring import router as app_logs_router
from api.nodes import router as nodes_router
from api.periodic_tasks import router as periodic_tasks_router
from api.pipelines import router as pipelines_router
from api.preview import router as preview_router
from api.profile import router as profile_router
from api.push import router as push_router
from api.repositories import router as repositories_router
from api.system_settings import router as system_settings_router
from api.tasks import router as tasks_router
from api.templates import router as templates_router
from api.users import router as users_router
from app_logging.config import configure_logging, get_logger
from db.session import engine
from services.errors import AppError
from ws.tasks import router as ws_router

configure_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("app_startup")
    yield
    await engine.dispose()
    logger.info("app_shutdown")


app = FastAPI(title="Tracker API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(tasks_router)
app.include_router(repositories_router)
app.include_router(templates_router)
app.include_router(preview_router)
app.include_router(llm_accounts_router)
app.include_router(env_variables_router)
app.include_router(mcp_servers_router)
app.include_router(pipelines_router)
app.include_router(nodes_router)
app.include_router(users_router)
app.include_router(profile_router)
app.include_router(periodic_tasks_router)
app.include_router(app_logs_router)
app.include_router(monitoring_router)
app.include_router(system_settings_router)
app.include_router(push_router)
app.include_router(ws_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = str(uuid.uuid4())
    logger.warning(
        "app_error",
        code=exc.code,
        error_message=exc.message,
        request_id=request_id,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = str(uuid.uuid4())
    logger.error(
        "unhandled_exception",
        error_type=type(exc).__name__,
        error_message=str(exc),
        request_id=request_id,
        path=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Внутренняя ошибка сервера",
                "request_id": request_id,
            }
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
