import time

from fastapi import APIRouter, HTTPException

from backend.schemas.resume_draft import ResumeDraftRequest, ResumeDraftResponse
from backend.services.monitor.run_store import add_event, get_run
from backend.services.resume.resume_draft_service import generate_resume_draft

router = APIRouter(prefix="/resume", tags=["resume"])


@router.post("/draft", response_model=ResumeDraftResponse)
def generate_resume_draft_endpoint(payload: ResumeDraftRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    result = generate_resume_draft(payload.model_dump())
    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        status = "completed"
        message = "Targeted resume draft generated"

        if len(result["tailored_experience_bullets"]) < 3:
            status = "warning"
            message = "Resume draft generated with limited experience bullet coverage"

        add_event(
            payload.run_id,
            {
                "step_name": "resume_generate",
                "step_type": "generation",
                "status": status,
                "message": message,
                "input_summary": {
                    "target_job_title": payload.job.title,
                    "target_company": payload.job.company,
                },
                "output_summary": {
                    "suggested_filename": result["suggested_filename"],
                    "skills_count": len(result["prioritized_skills"]),
                    "experience_bullets": len(result["tailored_experience_bullets"]),
                    "next_action": result["next_action"],
                },
                "latency_ms": latency_ms,
            }
        )

    return result