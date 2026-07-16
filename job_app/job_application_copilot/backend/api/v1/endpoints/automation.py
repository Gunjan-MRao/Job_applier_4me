from fastapi import APIRouter, HTTPException

from backend.schemas.automation import (
    AutomationStartRequest,
    AutomationStartResponse,
    AutomationStatusResponse,
)
from backend.services.automation_runtime import get_run, list_runs, start_run_thread

router = APIRouter(prefix="/automation", tags=["automation"])


@router.post("/start", response_model=AutomationStartResponse)
def start_automation(request: AutomationStartRequest):
    run = start_run_thread(request)
    return AutomationStartResponse(
        run_id=run["run_id"],
        status=run["status"],
        message="Automation run started successfully.",
    )


@router.get("/status/{run_id}", response_model=AutomationStatusResponse)
def get_automation_status(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return AutomationStatusResponse(**run)


@router.get("/runs")
def get_runs():
    return {"runs": list_runs()}