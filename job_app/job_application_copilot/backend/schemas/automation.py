from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class AutomationStartPayload(BaseModel):
    candidate_email: str
    keywords: List[str]
    location: str = "United Kingdom"
    auto_apply: bool = True
    track_live: bool = True
    resume_filename: Optional[str] = None
    resume_profile: Optional[dict] = None
    company_blacklist: Optional[List[str]] = None
    company_whitelist: Optional[List[str]] = None
    sponsorship_required: bool = False


# Aliases used by the automation endpoint router
AutomationStartRequest = AutomationStartPayload


class AutomationStartResponse(BaseModel):
    run_id: str
    status: str
    message: str


class AutomationStatusResponse(BaseModel):
    run_id: str
    candidate_email: str
    status: str
    stage: str
    progress_percent: int
    jobs_scanned: int
    jobs_matched: int
    jobs_applied: int
    jobs_failed: int = 0
    current_url: Optional[str] = None
    logs: List[Dict[str, Any]] = []
    result_summary: Optional[Dict[str, Any]] = None
    top_matches: List[Dict[str, Any]] = []
    applied_jobs: List[Dict[str, Any]] = []
    created_at: str
