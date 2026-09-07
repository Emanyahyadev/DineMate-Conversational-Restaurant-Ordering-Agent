"""DineMate API."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, menu, orders
from app.config import settings
from app.db import postgres
from app.services import memory_service
from app.services.errors import DomainError, ValidationError

logging.basicConfig(
    level=logging.INFO,
    format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is owned by Alembic; the app never creates tables.
    try:
        await postgres.ping()
    except Exception as exc:  # noqa: BLE001
        logger.error("postgres unreachable at startup: %s", exc)
    yield


app = FastAPI(
    title="DineMate",
    description="Conversational restaurant ordering agent.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=exc.to_payload(getattr(request.state, "request_id", None)),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    err = ValidationError("That request was not valid.", fields=exc.errors()[:5])
    return JSONResponse(
        status_code=400, content=err.to_payload(getattr(request.state, "request_id", None))
    )


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(menu.router)
app.include_router(orders.router)
app.include_router(orders.internal_router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/ready", tags=["ops"])
async def ready() -> JSONResponse:
    """Postgres is required; Mongo being down is degraded, not dead (KPI R06)."""
    checks = {"postgres": "ok", "mongo": "ok", "llm": "ok"}

    try:
        await postgres.ping()
    except Exception:  # noqa: BLE001
        checks["postgres"] = "unavailable"

    if not await memory_service.ping():
        checks["mongo"] = "unavailable"

    if not settings.deepseek_api_key and not settings.use_fake_llm:
        checks["llm"] = "unconfigured"

    if checks["postgres"] != "ok":
        status, code = "down", 503
    elif "unavailable" in checks.values() or "unconfigured" in checks.values():
        status, code = "degraded", 200
    else:
        status, code = "ok", 200

    return JSONResponse(status_code=code, content={"status": status, "checks": checks})
