"""
backend/api/router.py  —  mounts all sub-routers onto /api/v1
"""
from fastapi import APIRouter
from backend.api import runs, jobs, profile, export

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(runs.router,    prefix="/runs",    tags=["runs"])
api_router.include_router(jobs.router,    prefix="/jobs",    tags=["jobs"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(export.router,  prefix="/export",  tags=["export"])
