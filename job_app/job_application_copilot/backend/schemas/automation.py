from typing import List, Optional
from pydantic import BaseModel, Field


class AutomationStartRequest(BaseModel):
    candidate_email: str
    keywords: List[str] = Field(default_factory=list)
    location: str = "United Kingdom"
    # max_jobs removed — scans everything
    auto_apply: bool = True
    track_live: bool = True
    resume_filename: Optional[str] = None
    resume_profile: Optional[dict] = None
    company_blacklist: Optional[List[str]] = None
    company_whitelist: Optional[List[str]] = None


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
    jobs_failed: int
    current_url: Optional[str] = None
    logs: List[dict] = Field(default_factory=list)
    result_summary: Optional[dict] = None
    top_matches: Optional[List[dict]] = None
    applied_jobs: Optional[List[dict]] = None
    created_at: str
