import re


STOPWORDS = {
    "and", "the", "with", "for", "you", "your", "our", "are", "will", "this", "that",
    "from", "into", "using", "across", "have", "has", "had", "their", "they", "them",
    "role", "team", "support", "work", "working", "candidate", "job", "ability",
    "skills", "skill", "experience", "required", "preferred", "including", "within",
    "strong", "good", "high", "level", "based"
}


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def tokenize_text(value: str | None) -> list[str]:
    text = normalize_text(value)
    tokens = re.findall(r"[a-z0-9\+\-/&\.]+", text)
    return [t for t in tokens if len(t) > 2 and t not in STOPWORDS]


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def extract_priority_keywords(job: dict) -> list[str]:
    title_tokens = tokenize_text(job.get("title"))
    description_tokens = tokenize_text(job.get("description"))
    skills = [normalize_text(x) for x in job.get("skills", []) if x and x.strip()]

    repeated = []
    token_counts = {}
    for token in description_tokens:
        token_counts[token] = token_counts.get(token, 0) + 1

    for token, count in token_counts.items():
        if count >= 2:
            repeated.append(token)

    combined = skills + title_tokens + repeated
    combined = [x for x in combined if x]
    return unique_preserve_order(combined)[:20]


def profile_text(profile: dict) -> str:
    parts = []
    parts.append(profile.get("current_title") or "")
    parts.append(profile.get("summary") or "")
    parts.append(" ".join(profile.get("skills", [])))
    parts.append(" ".join(profile.get("experience_bullets", [])))
    parts.append(profile.get("education_summary") or "")
    parts.append(" ".join(profile.get("target_roles", [])))
    return normalize_text(" ".join(parts))


def analyze_keywords(profile: dict, job: dict) -> dict:
    priority = extract_priority_keywords(job)
    ptext = profile_text(profile)

    matched = []
    missing = []

    for keyword in priority:
        if keyword and keyword in ptext:
            matched.append(keyword)
        else:
            missing.append(keyword)

    return {
        "matched_keywords": matched,
        "missing_keywords": missing,
        "priority_keywords": priority,
    }


def build_summary_guidance(profile: dict, job: dict, keyword_analysis: dict) -> list[str]:
    guidance = []
    title = job.get("title")
    company = job.get("company")
    matched = keyword_analysis.get("matched_keywords", [])
    missing = keyword_analysis.get("missing_keywords", [])

    guidance.append(f"Open the summary with the target role title or a close equivalent, such as '{title}'.")
    if matched:
        guidance.append(f"Keep the strongest matching terms near the top of the summary: {', '.join(matched[:6])}.")
    if missing:
        guidance.append(f"Add truthful summary language for missing high-priority terms where defensible: {', '.join(missing[:5])}.")
    guidance.append(f"Frame the profile around relevance to {company} using domain-specific language from the posting, without copying full lines.")

    return guidance


def build_experience_guidance(profile: dict, job: dict, keyword_analysis: dict) -> list[str]:
    guidance = []
    matched = keyword_analysis.get("matched_keywords", [])
    missing = keyword_analysis.get("missing_keywords", [])
    title = job.get("title")

    guidance.append(f"Rewrite the top 2 to 3 experience bullets so they clearly support the '{title}' target.")
    if matched:
        guidance.append(f"Strengthen evidence around existing matches: {', '.join(matched[:6])}.")
    if missing:
        guidance.append(f"For missing terms, only add them where prior work genuinely supports them: {', '.join(missing[:6])}.")
    guidance.append("Prioritize measurable outcomes, system usage, coordination scope, reporting work, and process improvements over generic task descriptions.")

    return guidance


def skills_to_highlight(profile: dict, job: dict) -> list[str]:
    profile_skills = [normalize_text(x) for x in profile.get("skills", []) if x and x.strip()]
    job_skills = [normalize_text(x) for x in job.get("skills", []) if x and x.strip()]

    highlights = [skill for skill in job_skills if skill in profile_skills]
    return unique_preserve_order(highlights)[:12]


def caution_notes(profile: dict, job: dict, keyword_analysis: dict) -> list[str]:
    notes = []

    if keyword_analysis.get("missing_keywords"):
        notes.append("Do not add missing keywords unless they can be defended by actual experience or education.")

    description = normalize_text(job.get("description"))
    if "visa" in description or "sponsorship" in description:
        notes.append("Keep sponsorship-related wording consistent with the actual job posting and application answers.")

    if len(profile.get("experience_bullets", [])) < 3:
        notes.append("The profile has limited experience bullets; tailoring quality may improve after adding more role-specific bullet content.")

    return notes


def tailor_resume(payload: dict) -> dict:
    profile = payload["profile"]
    job = payload["job"]

    keyword_analysis = analyze_keywords(profile, job)

    return {
        "candidate_name": profile["candidate_name"],
        "target_job_title": job["title"],
        "target_company": job["company"],
        "keyword_analysis": keyword_analysis,
        "summary_rewrite_guidance": build_summary_guidance(profile, job, keyword_analysis),
        "experience_rewrite_guidance": build_experience_guidance(profile, job, keyword_analysis),
        "skills_to_highlight": skills_to_highlight(profile, job),
        "caution_notes": caution_notes(profile, job, keyword_analysis),
        "next_action": "generate_targeted_resume_draft",
    }