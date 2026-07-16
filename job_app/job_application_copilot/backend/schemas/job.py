from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Literal, Any


JobWorkMode = Literal["onsite", "hybrid", "remote", "unknown"]
JobFitLevel = Literal["strong", "moderate", "weak"]


class MatchingWeights(BaseModel):
    title: int = 20
    skills: int = 30
    seniority: int = 20
    location: int = 10
    sponsorship: int = 15
    education: int = 5


class MatchingPolicy(BaseModel):
    minimum_fit_score: int = 65
    shortlist_levels: list[JobFitLevel] = Field(default_factory=lambda: ["strong", "moderate"])

    require_sponsorship_if_needed: bool = False
    reject_when_sponsorship_unknown: bool = False

    use_max_seniority_gap: bool = True
    max_seniority_gap: int = 1

    location_strict: bool = False
    work_mode_strict: bool = False

    weights: MatchingWeights = Field(default_factory=MatchingWeights)


class JobRecord(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    work_mode: JobWorkMode = "unknown"
    description: str
    skills: list[str] = Field(default_factory=list)
    seniority: str = "entry-level"
    salary: Optional[str] = None
    sponsorship_available: Optional[bool] = None
    source: Optional[str] = None
    url: Optional[HttpUrl] = None


class RawJobRecord(BaseModel):
    title: Optional[str] = None
    job_title: Optional[str] = None

    company: Optional[str] = None
    employer: Optional[str] = None
    organization: Optional[str] = None

    location: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None

    work_mode: Optional[str] = None
    job_type: Optional[str] = None

    description: Optional[str] = None
    summary: Optional[str] = None

    skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    seniority: Optional[str] = None
    experience_level: Optional[str] = None

    salary: Optional[str] = None
    sponsorship_available: Optional[bool] = None

    source: Optional[str] = None
    url: Optional[HttpUrl] = None

    raw_payload: dict[str, Any] = Field(default_factory=dict)


class JobsImportRequest(BaseModel):
    run_id: Optional[str] = None
    source_name: str
    jobs: list[RawJobRecord] = Field(default_factory=list)


class JobsImportResponse(BaseModel):
    source_name: str
    raw_jobs_received: int
    normalized_jobs_count: int
    deduplicated_jobs_count: int
    dropped_jobs_count: int
    jobs: list[JobRecord] = Field(default_factory=list)


class JobsEvaluateRequest(BaseModel):
    run_id: Optional[str] = None

    candidate_name: str
    candidate_email: str
    target_roles: list[str] = Field(default_factory=list)
    resume_skills: list[str] = Field(default_factory=list)
    resume_roles: list[str] = Field(default_factory=list)
    education_summary: Optional[str] = None
    years_of_experience_hint: Optional[str] = None
    seniority_target: str = "entry-level"
    preferred_locations: list[str] = Field(default_factory=list)
    work_mode_preferences: list[str] = Field(default_factory=list)
    needs_visa_sponsorship: bool = False
    minimum_salary: Optional[str] = None

    policy: MatchingPolicy = Field(default_factory=MatchingPolicy)
    jobs: list[JobRecord] = Field(default_factory=list)


class JobFitResult(BaseModel):
    title: str
    company: str
    fit_score: int
    fit_level: JobFitLevel
    sponsorship_match: str
    hard_filter_passed: bool
    risk_flags: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommendation: str
    location: Optional[str] = None
    work_mode: JobWorkMode = "unknown"
    source: Optional[str] = None
    url: Optional[HttpUrl] = None


class JobsEvaluateResponse(BaseModel):
    candidate_name: str
    total_jobs_evaluated: int
    shortlisted_jobs: list[JobFitResult] = Field(default_factory=list)
    all_job_results: list[JobFitResult] = Field(default_factory=list)
    next_action: str