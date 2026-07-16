from typing import List, Optional
from pydantic import BaseModel


class AutomationStartPayload(BaseModel):
    candidate_email: str
    keywords: List[str]
    location: str = "United Kingdom"
    auto_apply: bool = True
    track_live: bool = True
    resume_filename: Optional[str] = None
    resume_profile: Optional[dict] = None
    company_blacklist: Optional[List[str]] = None
    company_whitelist: Optional[List[str]] = None
    sponsorship_required: bool = False   # new: filter out confirmed no-sponsorship roles
