import re


SUPPLY_CHAIN_KEYWORDS = {
    "supply chain", "logistics", "procurement", "inventory", "operations",
    "sap", "erp", "power bi", "excel", "order management", "import/export"
}

PROCUREMENT_KEYWORDS = {
    "procurement", "supplier", "po processing", "inventory", "sap", "erp", "excel"
}

OPERATIONS_KEYWORDS = {
    "operations", "workflow", "process improvement", "transaction management",
    "data analysis", "erp", "excel", "power bi"
}

TARGET_ROLE_PROFILES = {
    "entry-level supply chain analyst": {
        "keywords": {"supply chain", "logistics", "inventory", "erp", "sap", "excel", "power bi", "data analysis", "procurement"},
        "education_keywords": {"logistics", "supply chain"},
        "expected_seniority": {"entry-level", "junior", "graduate"},
    },
    "supply chain coordinator": {
        "keywords": {"supply chain", "logistics", "inventory", "procurement", "supplier", "order management", "erp", "excel"},
        "education_keywords": {"logistics", "supply chain"},
        "expected_seniority": {"entry-level", "junior"},
    },
    "procurement analyst": {
        "keywords": {"procurement", "supplier", "inventory", "sap", "erp", "excel", "data analysis"},
        "education_keywords": {"supply chain", "operations", "logistics"},
        "expected_seniority": {"entry-level", "junior"},
    },
    "operations analyst": {
        "keywords": {"operations", "workflow", "data analysis", "excel", "power bi", "erp", "process improvement"},
        "education_keywords": {"operations", "industrial", "logistics"},
        "expected_seniority": {"entry-level", "junior"},
    },
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_list(items: list[str]) -> list[str]:
    return [normalize_text(x) for x in items if x and x.strip()]


def infer_domain_keywords(skills: list[str], roles: list[str]) -> set[str]:
    merged = set(normalize_list(skills)) | set(normalize_list(roles))
    inferred = set()

    for item in merged:
        if any(k in item for k in SUPPLY_CHAIN_KEYWORDS):
            inferred.add(item)
        if any(k in item for k in PROCUREMENT_KEYWORDS):
            inferred.add(item)
        if any(k in item for k in OPERATIONS_KEYWORDS):
            inferred.add(item)

    return inferred


def score_single_role(
    target_role: str,
    resume_skills: list[str],
    resume_roles: list[str],
    years_of_experience_hint: str | None,
    seniority_target: str,
    education_summary: str | None,
    current_job_title: str | None,
) -> dict:
    target_role_norm = normalize_text(target_role)
    profile = TARGET_ROLE_PROFILES.get(
        target_role_norm,
        {
            "keywords": set(),
            "education_keywords": set(),
            "expected_seniority": {"entry-level", "junior"},
        },
    )

    normalized_skills = set(normalize_list(resume_skills))
    normalized_roles = set(normalize_list(resume_roles))
    inferred_keywords = infer_domain_keywords(resume_skills, resume_roles)

    evidence = []
    gaps = []
    score = 0

    skill_matches = sorted(profile["keywords"] & (normalized_skills | inferred_keywords))
    if skill_matches:
        skill_score = min(45, len(skill_matches) * 6)
        score += skill_score
        evidence.append(f"Relevant skill/domain matches: {', '.join(skill_matches[:8])}")
    else:
        gaps.append("Few direct keyword matches found for the target role")

    role_text = " ".join(normalized_roles)
    if target_role_norm in role_text:
        score += 20
        evidence.append("Resume already contains a closely matching job title")
    elif any(word in role_text for word in ["operations", "supply chain", "procurement", "logistics"]):
        score += 12
        evidence.append("Resume titles suggest adjacent functional experience")
    else:
        gaps.append("No direct prior job title match")

    edu_text = normalize_text(education_summary or "")
    edu_matches = [kw for kw in profile["education_keywords"] if kw in edu_text]
    if edu_matches:
        score += 20
        evidence.append(f"Education aligns with role domain: {', '.join(sorted(set(edu_matches)))}")
    else:
        gaps.append("Education does not clearly signal this target domain")

    seniority_norm = normalize_text(seniority_target)
    if seniority_norm in profile["expected_seniority"]:
        score += 10
        evidence.append(f"Target seniority aligns with role expectation: {seniority_target}")
    else:
        gaps.append("Requested seniority may not align with the target role profile")

    exp_text = normalize_text(years_of_experience_hint or "")
    if any(token in exp_text for token in ["1+", "2+", "3+", "4+", "5+", "year"]):
        score += 5
        evidence.append(f"Experience signal detected: {years_of_experience_hint}")

    current_title_text = normalize_text(current_job_title or "")
    if any(word in current_title_text for word in ["operations", "customer operations"]):
        score += 5
        evidence.append("Current role suggests operational process experience")

    score = max(0, min(score, 100))

    if score >= 75:
        fit_level = "strong"
        recommendation = "Proceed — this role looks like a strong application target."
    elif score >= 55:
        fit_level = "moderate"
        recommendation = "Proceed with tailoring — this role is relevant but should be customized carefully."
    else:
        fit_level = "weak"
        recommendation = "Review before applying — role fit is currently limited."

    if fit_level != "strong" and not gaps:
        gaps.append("Some signals are adjacent rather than directly role-specific")

    return {
        "target_role": target_role,
        "fit_score": score,
        "fit_level": fit_level,
        "matching_evidence": evidence,
        "gaps": gaps,
        "recommendation": recommendation,
    }


def score_candidate_roles(payload: dict) -> list[dict]:
    results = []
    for role in payload.get("target_roles", []):
        result = score_single_role(
            target_role=role,
            resume_skills=payload.get("resume_skills", []),
            resume_roles=payload.get("resume_roles", []),
            years_of_experience_hint=payload.get("years_of_experience_hint"),
            seniority_target=payload.get("seniority_target", "entry-level"),
            education_summary=payload.get("education_summary"),
            current_job_title=payload.get("current_job_title"),
        )
        results.append(result)

    return sorted(results, key=lambda x: x["fit_score"], reverse=True)