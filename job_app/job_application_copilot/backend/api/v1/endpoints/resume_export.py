import time

from fastapi import APIRouter, HTTPException

from backend.schemas.resume_export import ResumeExportRequest, ResumeExportResponse
from backend.services.monitor.run_store import add_event, get_run
from backend.services.resume.resume_export_service import export_resume_version

router = APIRouter(prefix="/resume", tags=["resume"])


@router.post("/export/{version_id}", response_model=ResumeExportResponse)
def export_resume_endpoint(version_id: str, payload: ResumeExportRequest):
    start = time.perf_counter()

    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="Provided run_id was not found")

    try:
        result = export_resume_version(
            version_id=version_id,
            export_format=payload.format,
            output_dir=payload.output_dir or "exports",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    latency_ms = int((time.perf_counter() - start) * 1000)

    if payload.run_id:
        add_event(
            payload.run_id,
            {
                "step_name": "resume_export",
                "step_type": "export",
                "status": "completed",
                "message": f"Resume exported as {result['format']}",
                "input_summary": {
                    "version_id": version_id,
                    "format": payload.format,
                },
                "output_summary": {
                    "filename": result["filename"],
                    "file_path": result["file_path"],
                    "next_action": result["next_action"],
                },
                "latency_ms": latency_ms,
            }
        )

    return result