# =============================================================================
# VIDATECH WIFI — FastAPI Application Entry Point
# backend/main.py
# =============================================================================

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from config import get_settings
from utils.keepalive import start_keepalive
from api import (
    users,
    packages,
    payments,
    sessions,
    devices,
    reports,
    settings as settings_router,
)
from auth import router as auth_router
from security.audit import log_event

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("vidatech")

settings = get_settings()


# ---------------------------------------------------------------------------
# Lifespan: runs on startup and shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    logger.info("Vidatech WiFi backend starting...")

    if settings.KEEPALIVE_ENABLED:
        await start_keepalive(
            url=settings.KEEPALIVE_URL,
            interval=settings.KEEPALIVE_INTERVAL_SECONDS,
        )
        logger.info("Keepalive task started.")

    logger.info(f"Environment : {settings.ENVIRONMENT}")
    logger.info(f"Daraja mode : {settings.DARAJA_ENV}")

    yield

    # SHUTDOWN
    logger.info("Vidatech WiFi backend shutting down.")


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if not settings.IS_PRODUCTION else None,   # hide docs in prod
    redoc_url="/redoc" if not settings.IS_PRODUCTION else None,
    openapi_url="/openapi.json" if not settings.IS_PRODUCTION else None,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# CORS — only allow your frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Reject requests with unexpected Host headers (prevents host header injection)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],   # tighten this to your Render domain in production
)


# ---------------------------------------------------------------------------
# Global exception handler — never leak stack traces to the client
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# ---------------------------------------------------------------------------
# Health check — used by keepalive and Render health checks
# ---------------------------------------------------------------------------
@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
API_PREFIX = "/api"

app.include_router(auth_router,           prefix=f"{API_PREFIX}/auth",     tags=["Auth"])
app.include_router(users.router,          prefix=f"{API_PREFIX}/users",    tags=["Users"])
app.include_router(packages.router,       prefix=f"{API_PREFIX}/packages", tags=["Packages"])
app.include_router(payments.router,       prefix=f"{API_PREFIX}/payments", tags=["Payments"])
app.include_router(sessions.router,       prefix=f"{API_PREFIX}/sessions", tags=["Sessions"])
app.include_router(devices.router,        prefix=f"{API_PREFIX}/devices",  tags=["Devices"])
app.include_router(reports.router,        prefix=f"{API_PREFIX}/reports",  tags=["Reports"])
app.include_router(settings_router.router,prefix=f"{API_PREFIX}/settings", tags=["Settings"])