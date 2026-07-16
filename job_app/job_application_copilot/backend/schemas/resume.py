from pydantic import BaseModel
from typing import List, Optional


class ResumeUploadResponse(BaseModel):
    filename: str
    saved_path: str
    content_type: str
    extracted_chars: int
    preview: str


class ResumeProfilePreview(BaseModel):
    filename: str
    candidate_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    skills: List[str]
    likely_roles: List[str]
    years_of_experience_hint: Optional[str]
    preview: str