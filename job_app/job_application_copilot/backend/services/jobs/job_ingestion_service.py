import re
from urllib.parse import urlparse


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_lower(value: str | None) -> str:
    return normalize_text(value).lower()


def pick_first(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            return value
    return None


def normalize_location(raw: dict) -> str | None:
    location = pick_first(raw.get("location"))
    if location:
        return normalize_text(location)

    city = normalize_text(raw.get("city"))
    region = normalize_text(raw.get("region"))

    if city and region:
        return f"{city}, {region}"
    if city:
        return city
    if region:
        return region
    return None


def normalize_work_mode(raw: dict) -> str:
    value = normalize_lower(
        pick_first(raw.get("work_mode"), raw.get("job_type"), raw.get("summary"), raw.get("description"))
    )

    if any(x in value for x in ["remote", "work from home", "wfh"]):
        return "remote"
    if any(x in value for x in ["hybrid"]):
        return "hybrid"
    if any(x in value for x in ["onsite", "on-site", "office based", "office-based"]):
        return "onsite"
    return "unknown"


def normalize_seniority(raw: dict) -> str:
    value = normalize_lower(
        pick_first(raw.get("seniority"), raw.get("experience_level"), raw.get("title"), raw.get("job_title"))
    )

    if any(x in value for x in ["intern"]):
        return "intern"
    if any(x in value for x in ["graduate", "entry"]):
        return "entry-level"
    if any(x in value for x in ["junior", "jr"]):
        return "junior"
    if any(x in value for x in ["associate"]):
        return "associate"
    if any(x in value for x in ["mid", "experienced"]):
        return "mid"
    if any(x in value for x in ["senior", "sr"]):
        return "senior"
    if any(x in value for x in ["lead"]):
        return "lead"
    if any(x in value for x in ["manager"]):
        return "manager"
    if any(x in value for x in ["head", "director"]):
        return "director"
    return "entry-level"


def normalize_skills(raw: dict) -> list[str]:
    values = []
    for field in ["skills", "tags"]:
        raw_value = raw.get(field)
        if isinstance(raw_value, list):
            values.extend(raw_value)

    cleaned = []
    seen = set()
    for item in values:
        text = normalize_lower(str(item))
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def normalize_job(raw: dict, source_name: str) -> dict | None:
    title = pick_first(raw.get("title"), raw.get("job_title"))
    company = pick_first(raw.get("company"), raw.get("employer"), raw.get("organization"))
    description = pick_first(raw.get("description"), raw.get("summary")) or ""

    title = normalize_text(title)
    company = normalize_text(company)
    description = normalize_text(description)

    if not title or not company:
        return None

    return {
        "title": title,
        "company": company,
        "location": normalize_location(raw),
        "work_mode": normalize_work_mode(raw),
        "description": description,
        "skills": normalize_skills(raw),
        "seniority": normalize_seniority(raw),
        "salary": normalize_text(raw.get("salary")) or None,
        "sponsorship_available": raw.get("sponsorship_available"),
        "source": normalize_text(raw.get("source")) or source_name,
        "url": raw.get("url"),
    }


def canonical_job_key(job: dict) -> str:
    title = normalize_lower(job.get("title"))
    company = normalize_lower(job.get("company"))
    location = normalize_lower(job.get("location"))
    return f"{title}|{company}|{location}"


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return None


def deduplicate_jobs(jobs: list[dict]) -> list[dict]:
    deduped = {}
    for job in jobs:
        key = canonical_job_key(job)

        if key not in deduped:
            deduped[key] = job
            continue

        existing = deduped[key]

        existing_desc_len = len(existing.get("description") or "")
        new_desc_len = len(job.get("description") or "")

        existing_has_url = bool(existing.get("url"))
        new_has_url = bool(job.get("url"))

        existing_domain = domain_from_url(existing.get("url"))
        new_domain = domain_from_url(job.get("url"))

        replace = False
        if not existing_has_url and new_has_url:
            replace = True
        elif new_desc_len > existing_desc_len:
            replace = True
        elif existing_domain is None and new_domain is not None:
            replace = True

        if replace:
            deduped[key] = job

    return list(deduped.values())


def import_jobs(payload: dict) -> dict:
    source_name = payload["source_name"]
    raw_jobs = payload.get("jobs", [])

    normalized = []
    dropped = 0

    for raw_job in raw_jobs:
        job = normalize_job(raw_job, source_name=source_name)
        if job:
            normalized.append(job)
        else:
            dropped += 1

    deduped = deduplicate_jobs(normalized)

    return {
        "source_name": source_name,
        "raw_jobs_received": len(raw_jobs),
        "normalized_jobs_count": len(normalized),
        "deduplicated_jobs_count": len(deduped),
        "dropped_jobs_count": dropped + (len(normalized) - len(deduped)),
        "jobs": deduped,
    }