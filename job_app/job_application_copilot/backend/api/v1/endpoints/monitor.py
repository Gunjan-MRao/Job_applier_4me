from fastapi import APIRouter, HTTPException

from backend.schemas.monitor import (
    WorkflowRunCreate,
    WorkflowRunResponse,
    StepEventCreate,
    StepEventResponse,
    RunAuditResponse,
)
from backend.services.monitor.monitor_service import audit_run
from backend.services.monitor.run_store import (
    add_event,
    create_run,
    get_run,
    list_events,
    list_runs,
    update_run_status,
)

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.post("/runs", response_model=WorkflowRunResponse)
def create_workflow_run(payload: WorkflowRunCreate):
    return create_run(payload.model_dump())


@router.get("/runs")
def get_workflow_runs():
    return list_runs()


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.patch("/runs/{run_id}/status", response_model=WorkflowRunResponse)
def patch_workflow_run_status(run_id: str, status: str):
    updated = update_run_status(run_id, status)
    if not updated:
        raise HTTPException(status_code=404, detail="Run not found")
    return updated


@router.post("/runs/{run_id}/events", response_model=StepEventResponse)
def create_step_event(run_id: str, payload: StepEventCreate):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return add_event(run_id, payload.model_dump())


@router.get("/runs/{run_id}/events")
def get_step_events(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return list_events(run_id)


@router.get("/runs/{run_id}/audit", response_model=RunAuditResponse)
def get_run_audit(run_id: str):
    return audit_run(run_id)