"""
backend/schemas/run_schemas.py
"""
from typing import List, Optional, Any
from pydantic import BaseModel, EmailStr


class ResumeProfile(BaseModel):
    candidate_name:           Optional[str] = None
    skills:                   List[str] = []
    years_of_experience_hint: Optional[str] = None
    likely_roles:             List[str] = []
    education:                Optional[str] = None
    linkedin_url:             Optional[str] = None


class RunRequest(BaseModel):
    candidate_email:     Optional[str] = None
    keywords:            List[str] = ["supply chain", "logistics", "procurement"]
    location:            str = "United Kingdom"
    auto_apply:          bool = True
    sponsorship_required: bool = False
    company_blacklist:   List[str] = []
    company_whitelist:   List[str] = []
    resume_profile:      Optional[ResumeProfile] = None


class RunResponse(BaseModel):
    run_id:  str
    status:  str
    stage:   Optional[str] = None
    created_at: str


class RunStatusResponse(BaseModel):
    run_id:           str
    status:           str
    stage:            Optional[str] = None
    progress_percent: int
    jobs_scanned:     int
    jobs_matched:     int
    jobs_applied:     int
    jobs_failed:      int
    current_url:      Optional[str] = None
    result_summary:   Optional[Any] = None
    created_at:       str
