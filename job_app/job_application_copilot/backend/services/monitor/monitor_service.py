"""
backend/services/monitor/monitor_service.py
Provides run health / stats snapshots for the dashboard.
"""
from backend.services.automation_runtime import list_runs


def get_dashboard_stats() -> dict:
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
