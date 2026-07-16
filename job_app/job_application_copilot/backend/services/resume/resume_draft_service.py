import re


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_lower(value: str | None) -> str:
    return normalize_text(value).lower()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", normalize_text(value))
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        key = normalize_lower(item)
        if key and key not in seen:
            seen.add(key)
            output.append(normalize_text(item))
    return output


def build_filename(candidate_name: str, company: str, job_title: str) -> str:
    first_name = normalize_text(candidate_name).split(" ")[0] if normalize_text(candidate_name) else "Candidate"
    return f"{slugify(first_name)}_Resume_{slugify(company)}_{slugify(job_title)}.txt"


def build_headline(profile: dict, job: dict) -> str:
    title = normalize_text(job.get("title"))
    current_title = normalize_text(profile.get("current_title"))
    target_roles = profile.get("target_roles", [])

    if title:
        return job["title"]

    if current_title:
        return profile["current_title"]

    if target_roles:
        return target_roles[0]

    return "Targeted Resume"


def build_summary(profile: dict, job: dict, keyword_analysis: dict) -> str:
    matched = keyword_analysis.get("matched_keywords", [])[:6]
    title = job.get("title")
    base_summary = normalize_text(profile.get("summary"))

    opening = f"{title} candidate with experience in "
    if matched:
        opening += ", ".join(matched[:-1]) + (f", and {matched[-1]}" if len(matched) > 1 else matched[0])
    else:
        opening += "operations, coordination, and job-relevant workflows"

    sentence2 = "Brings transferable experience across reporting, cross-functional coordination, and process support."
    sentence3 = "Targeted for ATS-safe alignment with the selected role while keeping claims grounded in real experience."

    if base_summary:
        return f"{opening}. {sentence2} {sentence3}"

    return f"{opening}. {sentence2} {sentence3}"


def prioritize_skills(profile: dict, guidance: dict, keyword_analysis: dict) -> list[str]:
    profile_skills = profile.get("skills", [])
    highlighted = guidance.get("skills_to_highlight", [])
    matched_keywords = keyword_analysis.get("matched_keywords", [])

    ordered = highlighted + matched_keywords + profile_skills
    return unique_preserve_order(ordered)[:15]


def build_experience_bullets(profile: dict, job: dict, keyword_analysis: dict) -> list[str]:
    original_bullets = profile.get("experience_bullets", [])
    matched = keyword_analysis.get("matched_keywords", [])[:6]

    generated = []

    if original_bullets:
        for idx, bullet in enumerate(original_bullets[:3], start=1):
            bullet_text = normalize_text(bullet)
            if idx == 1 and matched:
                generated.append(
                    f"Aligned prior operational work with {', '.join(matched[:4])} priorities through structured coordination, reporting, and workflow support."
                )
            elif idx == 2:
                generated.append(
                    "Supported cross-functional activities, maintained process visibility, and contributed to timely execution of operational tasks."
                )
            else:
                generated.append(
                    "Used systems, spreadsheets, and team coordination practices to support accurate tracking, updates, and day-to-day business operations."
                )

    while len(generated) < 3:
        generated.append("Add a verified bullet here based on real experience relevant to the target role.")

    return generated[:3]


def build_education_section(profile: dict) -> str:
    return normalize_text(profile.get("education_summary")) or "Add education details."


def build_ats_notes(keyword_analysis: dict, guidance: dict) -> list[str]:
    notes = [
        "Keep the final resume format simple and ATS-friendly with clear section headings.",
        "Use the target job title and strongest matching keywords naturally in summary and experience sections.",
        "Do not add unsupported claims, tools, or quantified outcomes."
    ]

    missing = keyword_analysis.get("missing_keywords", [])
    if missing:
        notes.append(f"Review whether these missing keywords can be supported truthfully: {', '.join(missing[:6])}.")

    for caution in guidance.get("caution_notes", []):
        notes.append(caution)

    return unique_preserve_order(notes)


def generate_resume_draft(payload: dict) -> dict:
    profile = payload["profile"]
    job = payload["job"]
    keyword_analysis = payload["keyword_analysis"]
    guidance = payload["guidance"]

    return {
        "candidate_name": profile["candidate_name"],
        "target_job_title": job["title"],
        "target_company": job["company"],
        "suggested_filename": build_filename(profile["candidate_name"], job["company"], job["title"]),
        "tailored_headline": build_headline(profile, job),
        "tailored_summary": build_summary(profile, job, keyword_analysis),
        "prioritized_skills": prioritize_skills(profile, guidance, keyword_analysis),
        "tailored_experience_bullets": build_experience_bullets(profile, job, keyword_analysis),
        "education_section": build_education_section(profile),
        "ats_notes": build_ats_notes(keyword_analysis, guidance),
        "next_action": "review_and_export_resume",
    }