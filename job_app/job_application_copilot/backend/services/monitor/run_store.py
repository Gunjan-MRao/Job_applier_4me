import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path("storage/logs")
RUNS_FILE = BASE_DIR / "workflow_runs.json"
EVENTS_FILE = BASE_DIR / "workflow_events.json"


def _ensure_files():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not RUNS_FILE.exists():
        RUNS_FILE.write_text("[]", encoding="utf-8")
    if not EVENTS_FILE.exists():
        EVENTS_FILE.write_text("[]", encoding="utf-8")


def _read_json(path: Path):
    _ensure_files()
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data):
    _ensure_files()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def create_run(payload: dict) -> dict:
    runs = _read_json(RUNS_FILE)
    run = {
        "run_id": str(uuid.uuid4()),
        "workflow_name": payload["workflow_name"],
        "status": "pending",
        "candidate_name": payload.get("candidate_name"),
        "candidate_email": payload.get("candidate_email"),
        "target_role": payload.get("target_role"),
        "notes": payload.get("notes"),
        "input_payload": payload.get("input_payload"),
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    runs.append(run)
    _write_json(RUNS_FILE, runs)
    return run


def list_runs() -> list[dict]:
    return _read_json(RUNS_FILE)


def get_run(run_id: str) -> dict | None:
    runs = _read_json(RUNS_FILE)
    for run in runs:
        if run["run_id"] == run_id:
            return run
    return None


def update_run_status(run_id: str, status: str) -> dict | None:
    runs = _read_json(RUNS_FILE)
    updated = None
    for run in runs:
        if run["run_id"] == run_id:
            run["status"] = status
            run["updated_at"] = _now_iso()
            updated = run
            break
    _write_json(RUNS_FILE, runs)
    return updated


def add_event(run_id: str, payload: dict) -> dict:
    events = _read_json(EVENTS_FILE)
    event = {
        "event_id": str(uuid.uuid4()),
        "run_id": run_id,
        "step_name": payload["step_name"],
        "step_type": payload.get("step_type", "generic"),
        "status": payload["status"],
        "message": payload.get("message"),
        "input_summary": payload.get("input_summary"),
        "output_summary": payload.get("output_summary"),
        "error_text": payload.get("error_text"),
        "latency_ms": payload.get("latency_ms"),
        "created_at": _now_iso(),
    }
    events.append(event)
    _write_json(EVENTS_FILE, events)

    if payload["status"] == "started":
        update_run_status(run_id, "running")
    elif payload["status"] == "failed":
        update_run_status(run_id, "failed")
    elif payload["status"] == "warning":
        update_run_status(run_id, "needs_review")

    return event


def list_events(run_id: str) -> list[dict]:
    events = _read_json(EVENTS_FILE)
    return [e for e in events if e["run_id"] == run_id]