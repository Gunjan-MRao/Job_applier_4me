from pydantic import BaseModel, Field
from typing import Optional


class ResumeDraftProfile(BaseModel):
    candidate_name: str
    candidate_email: str
    phone: Optional[str] = None
    current_title: Optional[str] = None
    location: Optional[str] = None
    summary: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    experience_bullets: list[str] = Field(default_factory=list)
    education_summary: Optional[str] = None
    target_roles: list[str] = Field(default_factory=list)


class ResumeDraftJob(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    description: str
    skills: list[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None


class ResumeDraftKeywordAnalysis(BaseModel):
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    priority_keywords: list[str] = Field(default_factory=list)


class ResumeDraftGuidance(BaseModel):
    summary_rewrite_guidance: list[str] = Field(default_factory=list)
    experience_rewrite_guidance: list[str] = Field(default_factory=list)
    skills_to_highlight: list[str] = Field(default_factory=list)
    caution_notes: list[str] = Field(default_factory=list)


class ResumeDraftRequest(BaseModel):
    run_id: Optional[str] = None
    profile: ResumeDraftProfile
    job: ResumeDraftJob
    keyword_analysis: ResumeDraftKeywordAnalysis
    guidance: ResumeDraftGuidance


class ResumeDraftResponse(BaseModel):
    candidate_name: str
    target_job_title: str
    target_company: str
    suggested_filename: str
    tailored_headline: str
    tailored_summary: str
    prioritized_skills: list[str] = Field(default_factory=list)
    tailored_experience_bullets: list[str] = Field(default_factory=list)
    education_section: str
    ats_notes: list[str] = Field(default_factory=list)
    next_action: str