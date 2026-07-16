"""
backend/services/search/search_service.py
In-memory job search / filter helper used by the Streamlit UI and API.
"""
from typing import List, Optional
from backend.services.automation_runtime import RUNS, RUN_LOCK


def search_jobs(
    run_id: Optional[str] = None,
    query:  Optional[str] = None,
    min_score: int = 0,
    sponsorship: Optional[str] = None,
    source: Optional[str] = None,
) -> List[dict]:
    """Search applied_jobs across runs (in-memory)."""
    jobs: List[dict] = []
    with RUN_LOCK:
        runs = [RUNS[run_id]] if run_id and run_id in RUNS else list(RUNS.values())
    for run in runs:
        for j in run.get("applied_jobs", []):
            if (j.get("fit_score") or 0) < min_score:
                continue
            if sponsorship and j.get("sponsorship_status") != sponsorship:
                continue
            if source and source.lower() not in (j.get("source") or "").lower():
                continue
            if query:
                haystack = ((j.get("title") or "") + " " + (j.get("company") or "")).lower()
                if query.lower() not in haystack:
                    continue
            jobs.append(j)
    jobs.sort(key=lambda x: x.get("fit_score") or 0, reverse=True)
    return jobs
