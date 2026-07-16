from pydantic import BaseModel, Field
from typing import Optional, Literal, List


# Extend to include 'pending' for backward compat with service layer
ApplicationStatus = Literal["draft", "ready", "submitted", "rejected", "interview", "pending"]


class ApplicationJobSnapshot(BaseModel):
    job_id: Optional[str] = None
    title: str
    company: str
    location: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None


class ApplicationPackageRequest(BaseModel):
    run_id: Optional[str] = None
    candidate_email: str
    candidate_name: str
    resume_version_id: str
    resume_format: Literal["txt", "docx", "pdf"]
    resume_filename: str
    resume_file_path: str
    job: ApplicationJobSnapshot
    notes: Optional[str] = None
    initial_status: ApplicationStatus = "draft"


class ApplicationRecord(BaseModel):
    """
    Flexible record — only fields the service actually stores are required.
    All resume/package fields are optional so the lighter application_service
    dict (which doesn't have resume_version_id etc.) always validates.
    """
    application_id: str
    candidate_email: str
    status: ApplicationStatus
    created_at: str
    updated_at: str

    # Job may come in as a nested snapshot OR as flat fields from legacy service
    job: Optional[ApplicationJobSnapshot] = None
    job_title: Optional[str] = None
    company: Optional[str] = None
    job_url: Optional[str] = None
    cover_letter: Optional[str] = None
    cold_email: Optional[str] = None
    fit_score: Optional[int] = None
    sponsorship: Optional[str] = None
    run_id: Optional[str] = None
    notes: Optional[str] = None

    # Optional full package fields
    candidate_name: Optional[str] = None
    resume_version_id: Optional[str] = None
    resume_format: Optional[str] = None
    resume_filename: Optional[str] = None
    resume_file_path: Optional[str] = None


class ApplicationPackageResponse(BaseModel):
    application_id: str
    candidate_email: str
    candidate_name: str
    resume_version_id: str
    resume_format: str
    resume_filename: str
    resume_file_path: str
    job: ApplicationJobSnapshot
    status: ApplicationStatus
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    next_action: str


class ApplicationListResponse(BaseModel):
    candidate_email: str
    total_applications: int          # was 'total' in service — now fixed everywhere
    applications: List[ApplicationRecord] = Field(default_factory=list)


class ApplicationStatusUpdateRequest(BaseModel):
    run_id: Optional[str] = None
    status: ApplicationStatus
    notes: Optional[str] = None


class ApplicationStatusUpdateResponse(BaseModel):
    application_id: str
    candidate_email: str
    status: ApplicationStatus
    updated_at: str
    notes: Optional[str] = None
    next_action: str
