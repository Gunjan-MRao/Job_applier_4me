"""
backend/services/application/application_service.py
Tracks application history — persisted to storage/applications.json.

Exposes:
  create_application_package()      — used by POST /applications/create-package
  get_applications_for_candidate()  — used by GET  /applications/{candidate_email}
  update_application_status()       — used by PATCH /applications/{id}/status
  record_application()              — legacy helper kept for backward compat
  get_all_applications()            — legacy helper kept for backward compat
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

_APP_PATH = Path("storage/applications.json")
_APP_PATH.parent.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load() -> list:
    if _APP_PATH.exists():
        try:
            return json.loads(_APP_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save(data: list) -> None:
    _APP_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_application_package(payload: dict) -> dict:
    """
    Creates and persists a new application record.
    Expects payload keys: candidate_email, job (dict with title/company/url),
    cover_letter, cold_email, fit_score, run_id (optional).
    Returns an ApplicationPackageResponse-compatible dict.
    """
    apps = _load()
    job = payload.get("job") or {}
    application_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    entry = {
        "application_id":  application_id,
        "candidate_email": payload.get("candidate_email", ""),
        "job_title":       job.get("title", ""),
        "company":         job.get("company", ""),
        "job_url":         job.get("url", ""),
        "cover_letter":    payload.get("cover_letter", ""),
        "cold_email":      payload.get("cold_email", ""),
        "fit_score":       payload.get("fit_score", 0),
        "sponsorship":     job.get("sponsorship_status", "unknown"),
        "status":          "draft",       # was 'pending' — not a valid ApplicationStatus literal
        "next_action":     "submit",
        "created_at":      now,
        "updated_at":      now,
        "run_id":          payload.get("run_id", ""),
    }
    apps.append(entry)
    _save(apps)
    return entry


def get_applications_for_candidate(candidate_email: str) -> dict:
    """
    Returns all applications for a given candidate email.
    Response shape matches ApplicationListResponse schema.
    FIX: key is now 'total_applications' (was 'total') to match schema.
    """
    apps = _load()
    matched = [a for a in apps if a.get("candidate_email", "").lower() == candidate_email.lower()]
    return {
        "candidate_email":    candidate_email,
        "total_applications": len(matched),   # KEY FIX: was 'total'
        "applications":       matched,
    }


def update_application_status(
    application_id: str,
    new_status: str,
    notes: Optional[str] = None,
) -> dict:
    """
    Updates the status of an application by ID.
    Raises ValueError if not found.
    Returns an ApplicationStatusUpdateResponse-compatible dict.
    """
    apps = _load()
    for app in apps:
        if app.get("application_id") == application_id or app.get("id") == application_id:
            app["status"]     = new_status
            app["updated_at"] = datetime.utcnow().isoformat()
            if notes:
                app["notes"] = notes
            _save(apps)
            return {
                "application_id":  application_id,
                "status":          new_status,
                "candidate_email": app.get("candidate_email", ""),
                "next_action":     _next_action(new_status),
                "updated_at":      app["updated_at"],
                "notes":           app.get("notes"),
            }
    raise ValueError(f"Application {application_id} not found")


def _next_action(status: str) -> str:
    return {
        "draft":      "review",
        "ready":      "submit",
        "pending":    "submit",
        "submitted":  "await_response",
        "interview":  "prepare",
        "offered":    "review_offer",
        "rejected":   "move_on",
        "withdrawn":  "closed",
    }.get(status.lower(), "review")


# ---------------------------------------------------------------------------
# Legacy helpers (kept for backward compat with old Streamlit app code)
# ---------------------------------------------------------------------------

def record_application(job: dict, profile: dict, cover_letter: str = "", cold_email: str = "") -> dict:
    return create_application_package({
        "candidate_email": profile.get("email", profile.get("candidate_name", "unknown")),
        "job": job,
        "cover_letter": cover_letter,
        "cold_email": cold_email,
        "fit_score": job.get("fit_score", 0),
    })


def get_all_applications() -> List[dict]:
    return _load()
