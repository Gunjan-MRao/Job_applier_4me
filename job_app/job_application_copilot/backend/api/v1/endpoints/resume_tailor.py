import time

from fastapi import APIRouter, HTTPException

from backend.schemas.resume_tailor import ResumeTailorRequest, ResumeTailorResponse
from backend.services.monitor.run_store import add_event, get_run
from backend.services.resume.resume_tailor_service import tailor_resume

router = APIRouter(prefix="/resume", tags=["resume"])


@router.post("/tailor", response_model=ResumeTailorResponse)
def tailor_resume_endpoint(payload: ResumeTailorRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    result = tailor_resume(payload.model_dump())
    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        missing_keywords = result["keyword_analysis"]["missing_keywords"]
        status = "completed"
        message = "Resume tailoring guidance generated"

        if len(missing_keywords) >= 8:
            status = "warning"
            message = "Resume tailoring completed but many priority keywords are still missing"

        add_event(
            payload.run_id,
            {
                "step_name": "resume_tailor",
                "step_type": "optimization",
                "status": status,
                "message": message,
                "input_summary": {
                    "target_job_title": payload.job.title,
                    "target_company": payload.job.company,
                },
                "output_summary": {
                    "matched_keywords": len(result["keyword_analysis"]["matched_keywords"]),
                    "missing_keywords": len(result["keyword_analysis"]["missing_keywords"]),
                    "skills_to_highlight": len(result["skills_to_highlight"]),
                    "next_action": result["next_action"],
                },
                "latency_ms": latency_ms,
            }
        )

    return result