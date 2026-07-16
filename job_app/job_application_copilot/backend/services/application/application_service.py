import uuid
from datetime import datetime, timezone

from backend.services.application.application_store import (
    save_application,
    list_applications,
    get_application_by_id,
    update_application_record,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_application_package(payload: dict) -> dict:
    application_id = str(uuid.uuid4())
    created_at = _now_iso()

    record = {
        "application_id": application_id,
        "candidate_email": payload["candidate_email"],
        "candidate_name": payload["candidate_name"],
        "resume_version_id": payload["resume_version_id"],
        "resume_format": payload["resume_format"],
        "resume_filename": payload["resume_filename"],
        "resume_file_path": payload["resume_file_path"],
        "job": payload["job"],
        "status": payload.get("initial_status", "draft"),
        "notes": payload.get("notes") or None,
        "created_at": created_at,
        "updated_at": created_at,
    }

    save_application(payload["candidate_email"], record)

    return {
        "application_id": application_id,
        "candidate_email": payload["candidate_email"],
        "candidate_name": payload["candidate_name"],
        "resume_version_id": payload["resume_version_id"],
        "resume_format": payload["resume_format"],
        "resume_filename": payload["resume_filename"],
        "resume_file_path": payload["resume_file_path"],
        "job": payload["job"],
        "status": record["status"],
        "notes": record["notes"],
        "created_at": created_at,
        "updated_at": created_at,
        "next_action": "review_or_submit_application",
    }


def get_applications_for_candidate(candidate_email: str) -> dict:
    apps = list_applications(candidate_email)
    apps = sorted(apps, key=lambda x: x["created_at"], reverse=True)

    return {
        "candidate_email": candidate_email,
        "total_applications": len(apps),
        "applications": apps,
    }


def update_application_status(application_id: str, new_status: str, notes: str | None) -> dict:
    record = get_application_by_id(application_id)
    if not record:
        raise ValueError("Application not found")

    updated = dict(record)
    updated["status"] = new_status
    if notes:
        updated["notes"] = notes
    updated["updated_at"] = _now_iso()

    update_application_record(application_id, updated)

    return {
        "application_id": application_id,
        "candidate_email": updated["candidate_email"],
        "status": updated["status"],
        "updated_at": updated["updated_at"],
        "notes": updated.get("notes"),
        "next_action": "refresh_application_tracker",
    }