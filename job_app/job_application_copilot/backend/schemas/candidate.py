from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal


FitLevel = Literal["strong", "moderate", "weak"]


class CandidateOnboardRequest(BaseModel):
    run_id: Optional[str] = None
    candidate_name: str
    candidate_email: EmailStr
    current_location: Optional[str] = None

    resume_skills: list[str] = Field(default_factory=list)
    resume_roles: list[str] = Field(default_factory=list)
    years_of_experience_hint: Optional[str] = None

    target_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    work_mode_preferences: list[str] = Field(default_factory=list)
    industries_of_interest: list[str] = Field(default_factory=list)

    needs_visa_sponsorship: bool = False
    seniority_target: str = "entry-level"
    minimum_salary: Optional[str] = None
    notes: Optional[str] = None

    education_summary: Optional[str] = None
    current_job_title: Optional[str] = None


class RoleFitDetail(BaseModel):
    target_role: str
    fit_score: int
    fit_level: FitLevel
    matching_evidence: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommendation: str


class CandidateOnboardResponse(BaseModel):
    candidate_name: str
    candidate_email: EmailStr
    seniority_target: str
    needs_visa_sponsorship: bool
    target_roles: list[str]
    role_fit_results: list[RoleFitDetail] = Field(default_factory=list)
    next_action: str