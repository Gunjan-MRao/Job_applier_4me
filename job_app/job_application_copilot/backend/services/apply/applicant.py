"""
backend/services/apply/applicant.py
Orchestrates cover letter + cold email generation for a single job.
Delegate to automation_runtime for LLM calls.
"""
from backend.services.automation_runtime import generate_cover_letter, generate_cold_email


def apply_to_job(profile: dict, job: dict) -> dict:
    """Returns dict with cover_letter and cold_email."""
    return {
        "cover_letter": generate_cover_letter(profile, job),
        "cold_email":   generate_cold_email(profile, job),
    }
