import time

from fastapi import APIRouter, HTTPException

from backend.schemas.candidate import CandidateOnboardRequest, CandidateOnboardResponse
from backend.services.match.role_fit_service import score_candidate_roles
from backend.services.monitor.run_store import add_event, get_run

router = APIRouter(prefix="/candidate", tags=["candidate"])


@router.post("/onboard", response_model=CandidateOnboardResponse)
def onboard_candidate(payload: CandidateOnboardRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    results = score_candidate_roles(payload.model_dump())
    next_action = "review_roles"

    if results:
        top_score = results[0]["fit_score"]
        if top_score >= 75:
            next_action = "search_jobs"
        elif top_score >= 55:
            next_action = "search_jobs_with_careful_tailoring"
        else:
            next_action = "refine_target_roles"

    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        top_result = results[0] if results else None
        status = "completed"
        message = "Candidate onboarding and role-fit scoring completed"

        if top_result and top_result["fit_score"] < 55:
            status = "warning"
            message = "Candidate onboarding completed but top role fit is weak"

        add_event(
            payload.run_id,
            {
                "step_name": "role_fit",
                "step_type": "matching",
                "status": status,
                "message": message,
                "input_summary": {
                    "target_roles_count": len(payload.target_roles),
                    "seniority_target": payload.seniority_target,
                    "needs_visa_sponsorship": payload.needs_visa_sponsorship,
                },
                "output_summary": {
                    "top_target_role": top_result["target_role"] if top_result else None,
                    "fit_score": top_result["fit_score"] if top_result else None,
                    "fit_level": top_result["fit_level"] if top_result else None,
                    "next_action": next_action,
                },
                "latency_ms": latency_ms,
            }
        )

    return {
        "candidate_name": payload.candidate_name,
        "candidate_email": payload.candidate_email,
        "seniority_target": payload.seniority_target,
        "needs_visa_sponsorship": payload.needs_visa_sponsorship,
        "target_roles": payload.target_roles,
        "role_fit_results": results,
        "next_action": next_action,
    }