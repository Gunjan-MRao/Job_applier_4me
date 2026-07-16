from pydantic import BaseModel, Field, HttpUrl
from typing import Optional


class CandidateResumeProfile(BaseModel):
    candidate_name: str
    candidate_email: str
    current_title: Optional[str] = None
    summary: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    experience_bullets: list[str] = Field(default_factory=list)
    education_summary: Optional[str] = None
    target_roles: list[str] = Field(default_factory=list)


class TailorTargetJob(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    description: str
    skills: list[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    source: Optional[str] = None
    url: Optional[HttpUrl] = None


class ResumeTailorRequest(BaseModel):
    run_id: Optional[str] = None
    profile: CandidateResumeProfile
    job: TailorTargetJob


class TailorKeywordAnalysis(BaseModel):
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    priority_keywords: list[str] = Field(default_factory=list)


class ResumeTailorResponse(BaseModel):
    candidate_name: str
    target_job_title: str
    target_company: str
    keyword_analysis: TailorKeywordAnalysis
    summary_rewrite_guidance: list[str] = Field(default_factory=list)
    experience_rewrite_guidance: list[str] = Field(default_factory=list)
    skills_to_highlight: list[str] = Field(default_factory=list)
    caution_notes: list[str] = Field(default_factory=list)
    next_action: str