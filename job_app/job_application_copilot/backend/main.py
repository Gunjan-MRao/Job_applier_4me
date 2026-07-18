import asyncio
import sys
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1.router import api_router
from backend.core.config import settings
from backend.db.engine import init_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows Proactor ConnectionResetError suppressor
# Fixes: "Exception in callback _ProactorBasePipeTransport._call_connection_lost"
# [WinError 10054] — harmless noise caused by Streamlit's HTTP client dropping
# keep-alive connections.  See uvicorn#1301, cpython#91227.
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    def _suppress_connection_reset(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
            return  # swallow silently
        # Everything else: log normally
        loop.default_exception_handler(context)

    async def _install_exception_handler():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_suppress_connection_reset)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    description="Generic resume-driven job search and application automation API."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("Database tables ensured.")
    if sys.platform == "win32":
        await _install_exception_handler()
        logger.info("Windows ConnectionResetError suppressor installed.")


@app.get("/")
def root() -> dict:
    return {
        "message": settings.app_name,
        "env": settings.app_env,
        "docs": "/docs",
        "health": "/health"
    }
