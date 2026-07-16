"""
backend/services/review/review_service.py
Allows the user to mark a job as saved, rejected, or applied externally.
State is persisted to storage/reviewed_jobs.json.
"""
import json
from pathlib import Path
from datetime import datetime

_REVIEW_PATH = Path("storage/reviewed_jobs.json")
_REVIEW_PATH.parent.mkdir(exist_ok=True)


def _load() -> dict:
    if _REVIEW_PATH.exists():
        try:
            return json.loads(_REVIEW_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict) -> None:
    _REVIEW_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def mark_job(url: str, status: str, notes: str = "") -> dict:
    """status: 'saved' | 'rejected' | 'applied' | 'interviewing'"""
    data = _load()
    data[url] = {
        "status":     status,
        "notes":      notes,
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save(data)
    return data[url]


def get_review(url: str) -> dict:
    return _load().get(url, {})


def get_all_reviews() -> dict:
    return _load()
