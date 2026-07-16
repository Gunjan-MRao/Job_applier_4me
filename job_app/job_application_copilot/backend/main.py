from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1.router import api_router
from backend.core.config import settings

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


@app.get("/")
def root() -> dict:
    return {
        "message": settings.app_name,
        "env": settings.app_env,
        "docs": "/docs",
        "health": "/health"
    }
