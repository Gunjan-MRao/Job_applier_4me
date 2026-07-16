import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.core.config import settings
from backend.schemas.resume import ResumeProfilePreview, ResumeUploadResponse
from backend.services.monitor.run_store import add_event
from backend.services.parser.resume_parser import build_profile_preview, extract_resume_text

router = APIRouter(prefix="/resume", tags=["resume"])

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def _validate_and_save_upload(file: UploadFile) -> tuple[str, Path]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")

    save_dir = Path(settings.resume_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename).name
    save_path = save_dir / safe_name

    with save_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return safe_name, save_path


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...)):
    safe_name, save_path = _validate_and_save_upload(file)

    try:
        text = extract_resume_text(save_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not extract text: {e}")

    return {
        "filename": safe_name,
        "saved_path": str(save_path),
        "content_type": file.content_type or "",
        "extracted_chars": len(text),
        "preview": text[:1000],
    }


@router.post("/parse", response_model=ResumeProfilePreview)
async def parse_resume(
    file: UploadFile = File(...),
    run_id: Optional[str] = Form(default=None),
):
    """
    Parse a resume file and return a structured profile.

    NOTE on run_id: automation runs are stored in-memory inside
    automation_runtime.py, NOT in run_store's JSON file.  We therefore
    no longer validate run_id existence here — if it is provided we still
    log the event, but we never reject the request on its account.
    """
    start = time.perf_counter()

    try:
        safe_name, save_path = _validate_and_save_upload(file)
        text = extract_resume_text(save_path)
        profile = build_profile_preview(safe_name, text)

        latency_ms = int((time.perf_counter() - start) * 1000)

        if run_id:
            try:
                add_event(
                    run_id,
                    {
                        "step_name": "resume_parse",
                        "step_type": "parser",
                        "status": "completed",
                        "message": "Resume parsed successfully",
                        "input_summary": {"filename": safe_name},
                        "output_summary": {
                            "candidate_name": profile.get("candidate_name"),
                            "email": profile.get("email"),
                            "skills_found": len(profile.get("skills", [])),
                        },
                        "latency_ms": latency_ms,
                    }
                )
            except Exception:
                pass  # logging is best-effort; never fail the request

        return profile

    except HTTPException:
        raise

    except Exception as e:
        if run_id:
            try:
                add_event(
                    run_id,
                    {
                        "step_name": "resume_parse",
                        "step_type": "parser",
                        "status": "failed",
                        "message": "Resume parse failed",
                        "error_text": str(e),
                        "latency_ms": int((time.perf_counter() - start) * 1000),
                    }
                )
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Could not parse resume: {e}")
