from pydantic import BaseModel, Field
from typing import Optional, Literal


ApplicationStatus = Literal["draft", "ready", "submitted", "rejected", "interview"]


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
    total_applications: int
    applications: list[ApplicationRecord] = Field(default_factory=list)


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