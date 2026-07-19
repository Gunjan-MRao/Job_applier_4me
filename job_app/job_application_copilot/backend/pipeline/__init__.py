"""backend.pipeline — the rebuilt, modular core job-application pipeline.

Flow: resume profile + preferences -> gather_jobs -> score -> draft -> ranked results.

Primary job source is the Adzuna API (official, free, UK-focused) with Reed as a
secondary; the legacy multi-board scraper is an opt-in, unreliable fallback and
mock listings are the last resort so the flow is always demoable with no keys.
"""
from backend.pipeline import drafting, job_sources, scoring
from backend.pipeline.orchestrator import gather_jobs, run_pipeline

__all__ = [
    "job_sources",
    "scoring",
    "drafting",
    "gather_jobs",
    "run_pipeline",
]
