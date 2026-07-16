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
    candidate_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: List[str] = []
    likely_roles: List[str] = []
    education: List[str] = []          # returned by build_profile_preview but was missing from schema
    years_of_experience_hint: Optional[str] = None
    preview: str = ""
