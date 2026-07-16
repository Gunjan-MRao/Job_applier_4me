"""
backend/api/jobs.py  —  job search & retrieval endpoints
"""
from fastapi import APIRouter, Query
from backend.db.crud import get_all_jobs, get_jobs_by_run

router = APIRouter()


@router.get("")
def list_jobs(
    run_id: str = Query(None, description="Filter by run ID"),
    min_score: int = Query(0, ge=0, le=100),
    sponsorship: str = Query(None, enum=["yes", "no", "unknown"]),
    limit: int = Query(100, ge=1, le=500),
):
    if run_id:
        jobs = get_jobs_by_run(run_id)
    else:
        jobs = get_all_jobs(limit=limit)
    if min_score:
        jobs = [j for j in jobs if (j.get("fit_score") or 0) >= min_score]
    if sponsorship:
        jobs = [j for j in jobs if j.get("sponsorship_status") == sponsorship]
    return {"jobs": jobs, "total": len(jobs)}
