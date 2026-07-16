import re


SENIORITY_ORDER = {
    "intern": 0,
    "graduate": 1,
    "entry-level": 1,
    "junior": 1,
    "associate": 2,
    "mid": 3,
    "mid-level": 3,
    "senior": 4,
    "lead": 5,
    "manager": 5,
    "head": 6,
    "director": 7,
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_list(items: list[str]) -> list[str]:
    return [normalize_text(x) for x in items if x and x.strip()]


def parse_salary_number(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.findall(r"\d+", value.replace(",", ""))
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


def infer_seniority_level(value: str) -> str:
    text = normalize_text(value)
    for level in ["director", "head", "manager", "lead", "senior", "mid-level", "mid", "associate", "junior", "entry-level", "graduate", "intern"]:
        if level in text:
            return level
    return "entry-level"


def seniority_gap(candidate_seniority: str, job_seniority: str) -> int:
    c = SENIORITY_ORDER.get(infer_seniority_level(candidate_seniority), 1)
    j = SENIORITY_ORDER.get(infer_seniority_level(job_seniority), 1)
    return max(0, j - c)


def passes_hard_filters(payload: dict, job: dict, policy: dict) -> tuple[bool, list[str]]:
    failures = []

    needs_sponsorship = payload.get("needs_visa_sponsorship", False)
    sponsorship_available = job.get("sponsorship_available")

    if needs_sponsorship and policy.get("require_sponsorship_if_needed"):
        if sponsorship_available is not True:
            failures.append("Sponsorship is required by policy but not confirmed")

    if needs_sponsorship and policy.get("reject_when_sponsorship_unknown"):
        if sponsorship_available is None:
            failures.append("Sponsorship is unknown and policy rejects unknown sponsorship")

    if policy.get("use_max_seniority_gap", True):
        gap = seniority_gap(payload.get("seniority_target", "entry-level"), job.get("seniority", "entry-level"))
        if gap > int(policy.get("max_seniority_gap", 1)):
            failures.append(f"Seniority gap exceeds policy limit: {gap}")

    if policy.get("location_strict"):
        preferred = set(normalize_list(payload.get("preferred_locations", [])))
        job_loc = normalize_text(job.get("location") or "")
        if preferred and not any(pref in job_loc or job_loc in pref for pref in preferred):
            failures.append("Job location does not meet strict location policy")

    if policy.get("work_mode_strict"):
        prefs = set(normalize_list(payload.get("work_mode_preferences", [])))
        mode = normalize_text(job.get("work_mode", "unknown"))
        if prefs and mode not in prefs:
            failures.append("Job work mode does not meet strict work mode policy")

    return len(failures) == 0, failures


def score_title(job_title: str, target_roles: list[str], weight: int) -> tuple[float, list[str]]:
    title = normalize_text(job_title)
    normalized_targets = normalize_list(target_roles)
    reasons = []
    raw = 0.0

    for target in normalized_targets:
        if target == title:
            raw = max(raw, 1.0)
            reasons.append(f"Job title exactly matches target role: {target}")
        elif any(word in title for word in target.split()):
            raw = max(raw, 0.7)
            reasons.append(f"Job title partially aligns with target role: {target}")

    return raw * weight, reasons


def score_skills(job_skills: list[str], resume_skills: list[str], description: str, weight: int) -> tuple[float, list[str], list[str]]:
    normalized_job_skills = set(normalize_list(job_skills))
    normalized_resume_skills = set(normalize_list(resume_skills))
    description_text = normalize_text(description)

    reasons = []
    gaps = []
    raw = 0.0

    if normalized_job_skills:
        matched = sorted(skill for skill in normalized_job_skills if skill in normalized_resume_skills)
        missing = sorted(skill for skill in normalized_job_skills if skill not in normalized_resume_skills)

        coverage = len(matched) / max(len(normalized_job_skills), 1)
        raw = min(1.0, coverage)

        if matched:
            reasons.append(f"Matched job skills: {', '.join(matched[:8])}")
        if missing:
            gaps.append(f"Potential missing job skills: {', '.join(missing[:8])}")

    desc_hits = []
    for skill in normalized_resume_skills:
        if skill and skill in description_text and skill not in normalized_job_skills:
            desc_hits.append(skill)

    if desc_hits:
        reasons.append(f"Resume skills also appear in description: {', '.join(sorted(desc_hits)[:8])}")
        raw = min(1.0, raw + 0.15)

    return raw * weight, reasons, gaps


def score_seniority(candidate_seniority: str, job_seniority: str, weight: int) -> tuple[float, list[str], list[str], list[str]]:
    reasons = []
    gaps = []
    risk_flags = []

    gap = seniority_gap(candidate_seniority, job_seniority)

    if gap == 0:
        raw = 1.0
        reasons.append(f"Seniority aligns: candidate={candidate_seniority}, job={job_seniority}")
    elif gap == 1:
        raw = 0.5
        reasons.append(f"Seniority is a manageable stretch: candidate={candidate_seniority}, job={job_seniority}")
        risk_flags.append("seniority_stretch")
    else:
        raw = 0.0
        gaps.append(f"Job seniority may be too advanced: {job_seniority}")
        risk_flags.append("seniority_mismatch")

    return raw * weight, reasons, gaps, risk_flags


def score_location(job_location: str | None, preferred_locations: list[str], work_mode: str, work_mode_preferences: list[str], weight: int) -> tuple[float, list[str], list[str]]:
    job_loc = normalize_text(job_location or "")
    preferred = set(normalize_list(preferred_locations))
    mode = normalize_text(work_mode)
    mode_prefs = set(normalize_list(work_mode_preferences))

    reasons = []
    gaps = []
    raw = 0.0

    location_ok = False
    mode_ok = False

    if not preferred:
        location_ok = True
    elif job_loc and any(pref in job_loc or job_loc in pref for pref in preferred):
        location_ok = True
        reasons.append(f"Location aligns with preference: {job_location}")

    if not mode_prefs:
        mode_ok = True
    elif mode and mode in mode_prefs:
        mode_ok = True
        reasons.append(f"Work mode aligns with preference: {work_mode}")
    elif mode != "unknown":
        gaps.append(f"Work mode differs from preference: {work_mode}")

    if location_ok and mode_ok:
        raw = 1.0
    elif location_ok or mode_ok:
        raw = 0.5
    else:
        raw = 0.0

    return raw * weight, reasons, gaps


def score_sponsorship(sponsorship_available: bool | None, needs_visa_sponsorship: bool, weight: int) -> tuple[float, str, list[str], list[str], list[str]]:
    reasons = []
    gaps = []
    risk_flags = []

    if not needs_visa_sponsorship:
        return weight, "not_needed", ["Visa sponsorship not required for this candidate"], [], []

    if sponsorship_available is True:
        return weight, "supported", ["Job indicates visa sponsorship support"], [], []

    if sponsorship_available is False:
        gaps.append("Job does not indicate visa sponsorship support")
        risk_flags.append("sponsorship_not_supported")
        return 0.0, "not_supported", reasons, gaps, risk_flags

    gaps.append("Visa sponsorship availability is unknown")
    risk_flags.append("sponsorship_unknown")
    return weight * 0.25, "unknown", reasons, gaps, risk_flags


def score_education(education_summary: str | None, description: str, title: str, weight: int) -> tuple[float, list[str]]:
    edu = normalize_text(education_summary or "")
    desc = normalize_text(description)
    title_text = normalize_text(title)

    reasons = []
    raw = 0.0

    if any(x in edu for x in ["logistics", "supply chain", "industrial engineering", "computer science", "data", "business", "finance"]):
        if any(x in desc or x in title_text for x in ["logistics", "supply chain", "procurement", "operations", "data", "analyst", "engineer", "finance"]):
            raw = 1.0
            reasons.append("Education is relevant to the job domain")
        else:
            raw = 0.5
            reasons.append("Education provides some domain support")

    return raw * weight, reasons


def evaluate_single_job(payload: dict, job: dict) -> dict:
    policy = payload.get("policy", {})
    weights = policy.get("weights", {})

    hard_ok, hard_failures = passes_hard_filters(payload, job, policy)

    total_score = 0.0
    reasons = []
    gaps = []
    risk_flags = []

    title_score, title_reasons = score_title(job["title"], payload.get("target_roles", []), weights.get("title", 20))
    total_score += title_score
    reasons.extend(title_reasons)

    skill_score, skill_reasons, skill_gaps = score_skills(
        job_skills=job.get("skills", []),
        resume_skills=payload.get("resume_skills", []),
        description=job.get("description", ""),
        weight=weights.get("skills", 30),
    )
    total_score += skill_score
    reasons.extend(skill_reasons)
    gaps.extend(skill_gaps)

    seniority_score, seniority_reasons, seniority_gaps, seniority_flags = score_seniority(
        candidate_seniority=payload.get("seniority_target", "entry-level"),
        job_seniority=job.get("seniority", "entry-level"),
        weight=weights.get("seniority", 20),
    )
    total_score += seniority_score
    reasons.extend(seniority_reasons)
    gaps.extend(seniority_gaps)
    risk_flags.extend(seniority_flags)

    location_score, location_reasons, location_gaps = score_location(
        job_location=job.get("location"),
        preferred_locations=payload.get("preferred_locations", []),
        work_mode=job.get("work_mode", "unknown"),
        work_mode_preferences=payload.get("work_mode_preferences", []),
        weight=weights.get("location", 10),
    )
    total_score += location_score
    reasons.extend(location_reasons)
    gaps.extend(location_gaps)

    sponsorship_score, sponsorship_label, sponsorship_reasons, sponsorship_gaps, sponsorship_flags = score_sponsorship(
        sponsorship_available=job.get("sponsorship_available"),
        needs_visa_sponsorship=payload.get("needs_visa_sponsorship", False),
        weight=weights.get("sponsorship", 15),
    )
    total_score += sponsorship_score
    reasons.extend(sponsorship_reasons)
    gaps.extend(sponsorship_gaps)
    risk_flags.extend(sponsorship_flags)

    education_score, education_reasons = score_education(
        education_summary=payload.get("education_summary"),
        description=job.get("description", ""),
        title=job.get("title", ""),
        weight=weights.get("education", 5),
    )
    total_score += education_score
    reasons.extend(education_reasons)

    min_salary = parse_salary_number(payload.get("minimum_salary"))
    job_salary = parse_salary_number(job.get("salary"))
    if min_salary and job_salary and job_salary < min_salary:
        gaps.append(f"Salary may be below preference: {job.get('salary')}")

    fit_score = max(0, min(int(round(total_score)), 100))

    if not hard_ok:
        fit_level = "weak"
        recommendation = "Do not shortlist — failed hard constraints."
        gaps.extend(hard_failures)
        risk_flags.append("hard_filter_failed")
    elif fit_score >= 80:
        fit_level = "strong"
        recommendation = "Shortlist this job."
    elif fit_score >= policy.get("minimum_fit_score", 65):
        fit_level = "moderate"
        recommendation = "Consider this job with tailored application materials."
    else:
        fit_level = "weak"
        recommendation = "Deprioritize unless the pipeline is sparse."

    return {
        "title": job["title"],
        "company": job["company"],
        "fit_score": fit_score,
        "fit_level": fit_level,
        "sponsorship_match": sponsorship_label,
        "hard_filter_passed": hard_ok,
        "risk_flags": sorted(set(risk_flags)),
        "reasons": reasons,
        "gaps": gaps,
        "recommendation": recommendation,
        "location": job.get("location"),
        "work_mode": job.get("work_mode", "unknown"),
        "source": job.get("source"),
        "url": job.get("url"),
    }


def evaluate_jobs(payload: dict) -> list[dict]:
    jobs = payload.get("jobs", [])
    results = [evaluate_single_job(payload, job) for job in jobs]
    return sorted(results, key=lambda x: (x["hard_filter_passed"], x["fit_score"]), reverse=True)