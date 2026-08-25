"""FastAPI application factory.

Wires the app described in `Architecture.md §9` as `api-service`: REST API, auth, and
project CRUD, with every error rendered in the `API.md §5` envelope.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import APIError, ErrorCode, build_error_body
from app.core.logging import configure_logging, get_logger
from app.core.metrics import registry as metrics_registry
from app.core.middleware import RequestIDMiddleware
from app.core.ratelimit import RateLimitMiddleware
from app.core.security import load_keys
from app.core.telemetry import instrument_app
from app.db.session import dispose_engine, get_engine
from app.services.storage_service import create_object_storage

logger = get_logger(__name__)

# Status codes mapped to the `API.md §5` code vocabulary, for exceptions that arrive as a
# bare HTTPException (e.g. FastAPI's own 405 / 404 for an unrouted path).
_STATUS_TO_CODE = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.UNPROCESSABLE_ENTITY,
    429: ErrorCode.RATE_LIMIT_EXCEEDED,
    503: ErrorCode.DEPENDENCY_UNAVAILABLE,
}


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open shared clients on startup, close them on shutdown."""
    settings = get_settings()

    load_keys(settings)

    app.state.redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
    )
    app.state.object_storage = create_object_storage(settings)
    engine = get_engine(settings)

    instrument_app(app, engine)

    logger.info("application_started", app_env=settings.app_env)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await dispose_engine()
        logger.info("application_stopped")


def register_exception_handlers(app: FastAPI) -> None:
    """Every error path renders the `API.md §5` envelope, so a client never has to parse
    two different error shapes."""

    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_body(
                code=exc.code,
                message=exc.message,
                request_id=_request_id(request),
                details=exc.details,
            ),
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                # Drop the leading "body"/"query" segment — the caller cares about the
                # field name, not our parameter plumbing.
                "field": ".".join(str(part) for part in error["loc"][1:]) or "request",
                "issue": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=400,
            content=build_error_body(
                code=ErrorCode.VALIDATION_ERROR,
                message="The request payload is invalid.",
                request_id=_request_id(request),
                details=details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_body(
                code=_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR),
                message=str(exc.detail),
                request_id=_request_id(request),
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the full traceback, return nothing about it. An internal error message can
        # carry a stack frame, a query fragment, or a connection string.
        logger.exception("unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content=build_error_body(
                code=ErrorCode.INTERNAL_ERROR,
                message="An internal error occurred.",
                request_id=_request_id(request),
            ),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    configure_logging(
        level=settings.log_level,
        # Human-readable locally, JSON everywhere Loki is scraping (`Deployment.md §11`).
        json_output=settings.app_env != "development",
    )

    app = FastAPI(
        title="APIWeaver Platform API",
        version="1.0.0",
        description=(
            "Agentic platform that generates API integrations from documentation. "
            "This spec is generated from the same normalization format the product "
            "produces for user-uploaded APIs."
        ),
        # API.md §7 — the spec is served under the version prefix it documents.
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Middleware is applied bottom-up, so the request-id middleware is added last to run
    # first — the rate limiter's error body needs a request_id already assigned.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )

    register_exception_handlers(app)

    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator(registry=metrics_registry).instrument(app).expose(app, include_in_schema=False)
    except (ImportError, ModuleNotFoundError):
        pass

    # Probes sit outside /api/v1: they are infrastructure contracts, not part of the
    # versioned product API, and must not move when v2 ships (`Architecture.md §11`).
    app.include_router(health.router)

    app.include_router(api_router)

    return app


app = create_app()
