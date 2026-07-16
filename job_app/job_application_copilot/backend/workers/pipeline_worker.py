"""
backend/workers/pipeline_worker.py
Optional Celery-style background worker wrapper.
Currently the pipeline runs in a daemon thread started by automation_runtime;
this module exposes a `run_pipeline_task` entry point for future
integration with Celery, RQ, or APScheduler.
"""
from backend.services.automation_runtime import run_automation_pipeline


def run_pipeline_task(run_id: str, payload) -> None:
    """Entry point for any task-queue system (Celery / RQ / APScheduler)."""
    run_automation_pipeline(run_id, payload)
