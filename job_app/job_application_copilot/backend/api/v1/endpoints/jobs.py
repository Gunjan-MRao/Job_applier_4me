import time

from fastapi import APIRouter, HTTPException

from backend.schemas.job import (
    JobsEvaluateRequest,
    JobsEvaluateResponse,
    JobsImportRequest,
    JobsImportResponse,
)
from backend.services.jobs.job_ingestion_service import import_jobs
from backend.services.match.job_fit_service import evaluate_jobs
from backend.services.monitor.run_store import add_event, get_run

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/import", response_model=JobsImportResponse)
def import_candidate_jobs(payload: JobsImportRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    result = import_jobs(payload.model_dump())
    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        status = "completed"
        message = "Job import completed"

        if result["deduplicated_jobs_count"] == 0:
            status = "warning"
            message = "Job import completed but produced zero usable jobs"

        add_event(
            payload.run_id,
            {
                "step_name": "job_search",
                "step_type": "ingestion",
                "status": status,
                "message": message,
                "input_summary": {
                    "source_name": payload.source_name,
                    "raw_jobs_received": len(payload.jobs),
                },
                "output_summary": {
                    "normalized_jobs_count": result["normalized_jobs_count"],
                    "deduplicated_jobs_count": result["deduplicated_jobs_count"],
                    "dropped_jobs_count": result["dropped_jobs_count"],
                    "jobs_found": result["deduplicated_jobs_count"],
                },
                "latency_ms": latency_ms,
            }
        )

    return result


@router.post("/evaluate", response_model=JobsEvaluateResponse)
def evaluate_candidate_jobs(payload: JobsEvaluateRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    results = evaluate_jobs(payload.model_dump())
    policy = payload.policy.model_dump()

    shortlist_levels = set(policy.get("shortlist_levels", ["strong", "moderate"]))
    minimum_fit_score = int(policy.get("minimum_fit_score", 65))

    shortlisted = [
        job for job in results
        if job["hard_filter_passed"]
        and job["fit_level"] in shortlist_levels
        and job["fit_score"] >= minimum_fit_score
        and "hard_filter_failed" not in job["risk_flags"]
        and "seniority_mismatch" not in job["risk_flags"]
    ]

    risky_shortlist_count = sum(
        1 for job in shortlisted
        if "sponsorship_unknown" in job["risk_flags"] or "seniority_stretch" in job["risk_flags"]
    )

    if shortlisted:
        next_action = "tailor_resume_for_shortlist"
    elif results:
        next_action = "broaden_job_search"
    else:
        next_action = "collect_jobs"

    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        top_result = results[0] if results else None
        status = "completed"
        message = "Job evaluation completed"

        if not results:
            status = "warning"
            message = "No jobs were provided for evaluation"
        elif not shortlisted:
            status = "warning"
            message = "Jobs evaluated but no safe shortlist was produced"
        elif risky_shortlist_count > 0:
            status = "warning"
            message = "Jobs evaluated but shortlist contains risk flags"

        add_event(
            payload.run_id,
            {
                "step_name": "job_match",
                "step_type": "matching",
                "status": status,
                "message": message,
                "input_summary": {
                    "jobs_count": len(payload.jobs),
                    "needs_visa_sponsorship": payload.needs_visa_sponsorship,
                    "target_roles_count": len(payload.target_roles),
                    "minimum_fit_score": minimum_fit_score,
                },
                "output_summary": {
                    "shortlisted_jobs": len(shortlisted),
                    "risky_shortlist_jobs": risky_shortlist_count,
                    "top_job_title": top_result["title"] if top_result else None,
                    "top_job_company": top_result["company"] if top_result else None,
                    "top_fit_score": top_result["fit_score"] if top_result else None,
                    "next_action": next_action,
                },
                "latency_ms": latency_ms,
            }
        )

    return {
        "candidate_name": payload.candidate_name,
        "total_jobs_evaluated": len(payload.jobs),
        "shortlisted_jobs": shortlisted,
        "all_job_results": results,
        "next_action": next_action,
    }