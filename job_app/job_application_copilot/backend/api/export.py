"""
backend/api/export.py  —  CSV / JSON export endpoints
"""
import csv
import io
import json
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from backend.db.crud import get_all_jobs

router = APIRouter()


@router.get("/csv")
def export_csv(min_score: int = Query(0, ge=0)):
    jobs = get_all_jobs(limit=5000)
    jobs = [j for j in jobs if (j.get("fit_score") or 0) >= min_score]
    if not jobs:
        return {"detail": "No jobs match the filter"}
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(jobs[0].keys()))
    writer.writeheader()
    writer.writerows(jobs)
    output.seek(0)
    return StreamingResponse(
        iter([output.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobs_export.csv"},
    )


@router.get("/json")
def export_json(min_score: int = Query(0, ge=0)):
    jobs = get_all_jobs(limit=5000)
    jobs = [j for j in jobs if (j.get("fit_score") or 0) >= min_score]
    content = json.dumps(jobs, indent=2, default=str)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=jobs_export.json"},
    )
