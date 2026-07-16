"""
backend/api/runs.py  —  pipeline run management endpoints
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from backend.schemas.run_schemas import RunRequest, RunResponse, RunStatusResponse
from backend.services.automation_runtime import (
    start_run_thread, get_run, list_runs,
)

router = APIRouter()


@router.post("", response_model=RunResponse, status_code=201)
def create_run(payload: RunRequest, background_tasks: BackgroundTasks):
    """Start a new job-search + apply run."""
    run = start_run_thread(payload)
    return run


@router.get("", response_model=list[RunStatusResponse])
def list_all_runs():
    return list_runs()


@router.get("/{run_id}", response_model=RunStatusResponse)
def get_run_status(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/logs")
def get_run_logs(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"logs": run.get("logs", [])}


@router.get("/{run_id}/results")
def get_run_results(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "top_matches":  run.get("top_matches", []),
        "applied_jobs": run.get("applied_jobs", []),
        "summary":      run.get("result_summary"),
    }
