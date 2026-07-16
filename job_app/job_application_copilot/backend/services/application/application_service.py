"""
backend/services/application/application_service.py
Tracks application history — persisted to storage/applications.json.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

_APP_PATH = Path("storage/applications.json")
_APP_PATH.parent.mkdir(exist_ok=True)


def _load() -> list:
    if _APP_PATH.exists():
        try:
            return json.loads(_APP_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save(data: list) -> None:
    _APP_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def record_application(job: dict, profile: dict, cover_letter: str = "", cold_email: str = "") -> dict:
    apps = _load()
    entry = {
        "id":           str(uuid.uuid4()),
        "job_title":    job.get("title", ""),
        "company":      job.get("company", ""),
        "job_url":      job.get("url", ""),
        "candidate":    profile.get("candidate_name", ""),
        "cover_letter": cover_letter,
        "cold_email":   cold_email,
        "fit_score":    job.get("fit_score", 0),
        "sponsorship":  job.get("sponsorship_status", "unknown"),
        "applied_at":   datetime.utcnow().isoformat(),
        "status":       "sent",
    }
    apps.append(entry)
    _save(apps)
    return entry


def get_all_applications() -> List[dict]:
    return _load()


def update_application_status(app_id: str, status: str) -> dict:
    apps = _load()
    for a in apps:
        if a["id"] == app_id:
            a["status"]     = status
            a["updated_at"] = datetime.utcnow().isoformat()
    _save(apps)
    return {"app_id": app_id, "status": status}
