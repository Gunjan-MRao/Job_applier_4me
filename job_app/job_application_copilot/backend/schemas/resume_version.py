from pydantic import BaseModel, Field
from typing import Optional


class ResumeVersionDraftPayload(BaseModel):
    suggested_filename: str
    tailored_headline: str
    tailored_summary: str
    prioritized_skills: list[str] = Field(default_factory=list)
    tailored_experience_bullets: list[str] = Field(default_factory=list)
    education_section: str
    ats_notes: list[str] = Field(default_factory=list)


class ResumeVersionRequest(BaseModel):
    run_id: Optional[str] = None
    candidate_name: str
    candidate_email: str
    target_job_title: str
    target_company: str
    source_job_url: Optional[str] = None
    notes: Optional[str] = None
    draft: ResumeVersionDraftPayload


class ResumeVersionRecord(BaseModel):
    version_id: str
    candidate_name: str
    candidate_email: str
    target_job_title: str
    target_company: str
    source_job_url: Optional[str] = None
    notes: Optional[str] = None
    suggested_filename: str
    export_text: str
    tailored_headline: str
    tailored_summary: str
    prioritized_skills: list[str] = Field(default_factory=list)
    tailored_experience_bullets: list[str] = Field(default_factory=list)
    education_section: str
    ats_notes: list[str] = Field(default_factory=list)
    created_at: str


class ResumeVersionResponse(BaseModel):
    version_id: str
    candidate_name: str
    candidate_email: str
    target_job_title: str
    target_company: str
    suggested_filename: str
    created_at: str
    export_text: str
    next_action: str


class ResumeVersionListResponse(BaseModel):
    candidate_email: str
    total_versions: int
    versions: list[ResumeVersionRecord] = Field(default_factory=list)