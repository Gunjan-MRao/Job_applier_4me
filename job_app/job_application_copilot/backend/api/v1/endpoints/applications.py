import time

from fastapi import APIRouter, HTTPException

from backend.schemas.application_package import (
    ApplicationPackageRequest,
    ApplicationPackageResponse,
    ApplicationListResponse,
    ApplicationStatusUpdateRequest,
    ApplicationStatusUpdateResponse,
)
from backend.services.monitor.run_store import add_event, get_run
from backend.services.application.application_service import (
    create_application_package,
    get_applications_for_candidate,
    update_application_status,
)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("/create-package", response_model=ApplicationPackageResponse)
def create_application_package_endpoint(payload: ApplicationPackageRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    result = create_application_package(payload.model_dump())
    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        add_event(
            payload.run_id,
            {
                "step_name": "application_package",
                "step_type": "storage",
                "status": "completed",
                "message": "Application package created",
                "input_summary": {
                    "candidate_email": payload.candidate_email,
                    "job_title": payload.job.title,
                    "job_company": payload.job.company,
                },
                "output_summary": {
                    "application_id": result["application_id"],
                    "status": result["status"],
                    "next_action": result["next_action"],
                },
                "latency_ms": latency_ms,
            },
        )

    return result


@router.get("/{candidate_email}", response_model=ApplicationListResponse)
def list_applications_endpoint(candidate_email: str):
    return get_applications_for_candidate(candidate_email)


@router.patch("/{application_id}/status", response_model=ApplicationStatusUpdateResponse)
def update_application_status_endpoint(application_id: str, payload: ApplicationStatusUpdateRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    try:
        result = update_application_status(
            application_id=application_id,
            new_status=payload.status,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        add_event(
            payload.run_id,
            {
                "step_name": "application_status_update",
                "step_type": "update",
                "status": "completed",
                "message": f"Application status updated to {payload.status}",
                "input_summary": {
                    "application_id": application_id,
                    "status": payload.status,
                },
                "output_summary": {
                    "candidate_email": result["candidate_email"],
                    "next_action": result["next_action"],
                },
                "latency_ms": latency_ms,
            },
        )

    return result