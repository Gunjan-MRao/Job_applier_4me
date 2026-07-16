"""
backend/services/monitor/monitor_service.py
Provides run health / stats snapshots for the dashboard.
"""
from backend.services.monitor.run_store import get_run, list_events


def get_dashboard_stats() -> dict:
    from backend.services.automation_runtime import list_runs
    runs = list_runs()
    total_runs    = len(runs)
    running_runs  = sum(1 for r in runs if r.get("status") == "running")
    completed     = sum(1 for r in runs if r.get("status") == "completed")
    total_scanned = sum(r.get("jobs_scanned", 0) for r in runs)
    total_matched = sum(r.get("jobs_matched", 0) for r in runs)
    total_applied = sum(r.get("jobs_applied", 0) for r in runs)
    return {
        "total_runs":    total_runs,
        "running_runs":  running_runs,
        "completed_runs": completed,
        "total_scanned": total_scanned,
        "total_matched": total_matched,
        "total_applied": total_applied,
        "runs":          runs,
    }


def audit_run(run_id: str) -> dict:
    """Return a run plus all its step events as an audit trail."""
    run = get_run(run_id)
    if not run:
        return {"run_id": run_id, "run": None, "events": [], "error": "Run not found"}
    events = list_events(run_id)
    return {
        "run_id": run_id,
        "run": run,
        "events": events,
        "total_steps": len(events),
        "errors": [e for e in events if e.get("status") == "error"],
    }
