from pydantic import BaseModel
from typing import Optional


class ResumeExportRequest(BaseModel):
    run_id: Optional[str] = None
    format: str
    output_dir: Optional[str] = "exports"


class ResumeExportResponse(BaseModel):
    version_id: str
    format: str
    file_path: str
    filename: str
    exported_at: str
    next_action: str