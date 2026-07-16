"""
backend/schemas/profile_schemas.py
"""
from typing import List, Optional
from pydantic import BaseModel


class ProfileIn(BaseModel):
    candidate_name:           Optional[str] = None
    candidate_email:          Optional[str] = None
    phone:                    Optional[str] = None
    linkedin_url:             Optional[str] = None
    skills:                   List[str] = []
    years_of_experience_hint: Optional[str] = None
    likely_roles:             List[str] = []
    education:                Optional[str] = None
    visa_status:              Optional[str] = None
    target_salary:            Optional[str] = None
    preferred_locations:      List[str] = []


class ProfileOut(ProfileIn):
    pass
