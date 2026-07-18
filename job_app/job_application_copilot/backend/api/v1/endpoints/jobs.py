"""
backend/api/v1/endpoints/jobs.py  — job search, retrieval, and lead lookup
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from backend.db.crud import get_all_jobs, get_jobs_by_run
from backend.services.lead_finder import find_recruiter_email, _guess_domain

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    run_id:      Optional[str] = Query(None,  description="Filter by run ID"),
    min_score:   int           = Query(0,     ge=0, le=100),
    sponsorship: Optional[str] = Query(None,  enum=["yes", "no", "unknown"]),
    limit:       int           = Query(100,   ge=1, le=500),
):
    """List jobs, optionally filtered by run, minimum fit score, or sponsorship status."""
    if run_id:
        jobs = get_jobs_by_run(run_id)
    else:
        jobs = get_all_jobs(limit=limit)
    if min_score:
        jobs = [j for j in jobs if (j.get("fit_score") or 0) >= min_score]
    if sponsorship:
        jobs = [j for j in jobs if j.get("sponsorship_status") == sponsorship]
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/{job_id}/lead")
async def get_job_lead(
    job_id:    str,
    run_id:    Optional[str] = Query(None, description="Run ID to look up the job from"),
    job_title: str           = Query("",   description="Job title hint for Apollo search"),
    company:   str           = Query("",   description="Company name"),
    domain:    Optional[str] = Query(None, description="Company domain e.g. tesco.com"),
):
    """
    Find the best recruiter / HR contact email for a specific job.

    The Streamlit frontend calls this endpoint before firing a cold email so
    the user can see the discovered contact before sending.  The endpoint
    tries Hunter.io → Apollo.io → heuristic in order and returns whichever
    strategy succeeded.

    Returns:
        {
            "email":    "talent@tesco.com",
            "strategy": "hunter" | "apollo" | "heuristic",
            "company":  "Tesco"
        }
    """
    if not company:
        # Try to resolve company from the job record if a run_id was provided
        if run_id:
            jobs = get_jobs_by_run(run_id)
            matched = [j for j in jobs if str(j.get("id", "")) == job_id
                       or j.get("url", "").endswith(job_id)]
            if matched:
                company = matched[0].get("company", "")
                job_title = job_title or matched[0].get("title", "")
                domain = domain or matched[0].get("domain")
        if not company:
            raise HTTPException(
                status_code=422,
                detail="'company' query parameter is required when job record cannot be resolved"
            )

    resolved_domain = domain or _guess_domain(company)
    result = await find_recruiter_email(
        company=company,
        domain=resolved_domain,
        job_title=job_title,
    )
    return result
