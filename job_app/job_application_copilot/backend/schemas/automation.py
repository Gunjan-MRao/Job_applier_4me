from typing import List, Optional, Literal
from pydantic import BaseModel, Field, EmailStr


RunStatus = Literal["queued", "running", "completed", "failed"]
RunStage = Literal[
    "queued",
    "loading_profile",
    "searching_jobs",
    "screening_jobs",
    "applying",
    "saving_results",
    "completed",
    "failed",
]


class AutomationStartRequest(BaseModel):
    candidate_email: EmailStr
    keywords: List[str] = Field(default_factory=list)
    location: str = "UK"
    max_jobs: int = 25
    auto_apply: bool = True
    track_live: bool = True


class AutomationStartResponse(BaseModel):
    run_id: str
    status: RunStatus
    message: str


class AutomationLogEntry(BaseModel):
    ts: str
    level: str
    message: str


class AutomationStatusResponse(BaseModel):
    run_id: str
    candidate_email: EmailStr
    status: RunStatus
    stage: RunStage
    progress_percent: int
    jobs_scanned: int
    jobs_matched: int
    jobs_applied: int
    jobs_failed: int
    current_url: Optional[str] = None
    logs: List[AutomationLogEntry] = Field(default_factory=list)
    result_summary: Optional[dict] = None