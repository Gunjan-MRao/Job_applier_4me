from fastapi import APIRouter
from backend.api.v1.endpoints.health import router as health_router
from backend.api.v1.endpoints.resume import router as resume_router
from backend.api.v1.endpoints.resume_tailor import router as resume_tailor_router
from backend.api.v1.endpoints.resume_draft import router as resume_draft_router
from backend.api.v1.endpoints.resume_versions import router as resume_versions_router
from backend.api.v1.endpoints.resume_export import router as resume_export_router
from backend.api.v1.endpoints.monitor import router as monitor_router
from backend.api.v1.endpoints.candidate import router as candidate_router
from backend.api.v1.endpoints.jobs import router as jobs_router
from backend.api.v1.endpoints.applications import router as applications_router
from backend.api.v1.endpoints.automation import router as automation_router
from backend.api.v1.endpoints.jobs_international import router as jobs_international_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(resume_router)
api_router.include_router(resume_tailor_router)
api_router.include_router(resume_draft_router)
api_router.include_router(resume_versions_router)
api_router.include_router(resume_export_router)
api_router.include_router(applications_router)
api_router.include_router(monitor_router)
api_router.include_router(candidate_router)
api_router.include_router(jobs_router)
api_router.include_router(automation_router)
api_router.include_router(jobs_international_router)
