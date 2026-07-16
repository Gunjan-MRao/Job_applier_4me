import uuid
from datetime import datetime, timezone

from backend.services.resume.version_store import save_resume_version, list_resume_versions


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def assemble_export_text(payload: dict) -> str:
    draft = payload["draft"]
    candidate_name = payload["candidate_name"]
    candidate_email = payload["candidate_email"]
    target_job_title = payload["target_job_title"]
    target_company = payload["target_company"]

    parts = [
        candidate_name,
        candidate_email,
        "",
        draft["tailored_headline"],
        "",
        "PROFESSIONAL SUMMARY",
        draft["tailored_summary"],
        "",
        "CORE SKILLS",
        ", ".join(draft.get("prioritized_skills", [])),
        "",
        "PROFESSIONAL EXPERIENCE",
    ]

    for bullet in draft.get("tailored_experience_bullets", []):
        parts.append(f"- {bullet}")

    parts.extend([
        "",
        "EDUCATION",
        draft.get("education_section", ""),
        "",
        "ATS NOTES",
    ])

    for note in draft.get("ats_notes", []):
        parts.append(f"- {note}")

    parts.extend([
        "",
        f"Target Role: {target_job_title}",
        f"Target Company: {target_company}",
    ])

    return "\n".join(parts).strip()


def create_resume_version(payload: dict) -> dict:
    version_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    export_text = assemble_export_text(payload)
    draft = payload["draft"]

    record = {
        "version_id": version_id,
        "candidate_name": payload["candidate_name"],
        "candidate_email": payload["candidate_email"],
        "target_job_title": payload["target_job_title"],
        "target_company": payload["target_company"],
        "source_job_url": payload.get("source_job_url"),
        "notes": normalize_text(payload.get("notes")) or None,
        "suggested_filename": draft["suggested_filename"],
        "export_text": export_text,
        "tailored_headline": draft["tailored_headline"],
        "tailored_summary": draft["tailored_summary"],
        "prioritized_skills": draft.get("prioritized_skills", []),
        "tailored_experience_bullets": draft.get("tailored_experience_bullets", []),
        "education_section": draft.get("education_section", ""),
        "ats_notes": draft.get("ats_notes", []),
        "created_at": created_at,
    }

    save_resume_version(payload["candidate_email"], record)

    return {
        "version_id": version_id,
        "candidate_name": payload["candidate_name"],
        "candidate_email": payload["candidate_email"],
        "target_job_title": payload["target_job_title"],
        "target_company": payload["target_company"],
        "suggested_filename": draft["suggested_filename"],
        "created_at": created_at,
        "export_text": export_text,
        "next_action": "export_resume_file",
    }


def get_resume_versions(candidate_email: str) -> dict:
    versions = list_resume_versions(candidate_email)
    versions = sorted(versions, key=lambda x: x["created_at"], reverse=True)

    return {
        "candidate_email": candidate_email,
        "total_versions": len(versions),
        "versions": versions,
    }