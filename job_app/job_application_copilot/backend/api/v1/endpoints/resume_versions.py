import time

from fastapi import APIRouter, HTTPException

from backend.schemas.resume_version import (
    ResumeVersionRequest,
    ResumeVersionResponse,
    ResumeVersionListResponse,
)
from backend.services.monitor.run_store import add_event, get_run
from backend.services.resume.resume_version_service import (
    create_resume_version,
    get_resume_versions,
)

router = APIRouter(prefix="/resume", tags=["resume"])


@router.post("/save-version", response_model=ResumeVersionResponse)
def save_resume_version_endpoint(payload: ResumeVersionRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    result = create_resume_version(payload.model_dump())
    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        status = "completed"
        message = "Resume version saved"

        if not result["export_text"].strip():
            status = "warning"
            message = "Resume version saved but export text is empty"

        add_event(
            payload.run_id,
            {
                "step_name": "resume_save",
                "step_type": "storage",
                "status": status,
                "message": message,
                "input_summary": {
                    "target_job_title": payload.target_job_title,
                    "target_company": payload.target_company,
                },
                "output_summary": {
                    "version_id": result["version_id"],
                    "suggested_filename": result["suggested_filename"],
                    "next_action": result["next_action"],
                },
                "latency_ms": latency_ms,
            }
        )

    return result


@router.get("/versions/{candidate_email}", response_model=ResumeVersionListResponse)
def list_resume_versions_endpoint(candidate_email: str):
    return get_resume_versions(candidate_email)