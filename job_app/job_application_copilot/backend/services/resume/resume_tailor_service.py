"""
backend/services/resume/resume_tailor_service.py
Generates targeted resume-tailoring bullet points for a given job.
Uses LLM if available; gracefully falls back to a keyword-diff approach.
"""
from typing import Optional


def tailor_resume(data: dict) -> dict:
    """
    Parameters
    ----------
    data : {"profile": {...}, "job": {...}}

    Returns
    -------
    dict with keys:
        headline       – one-line positioning statement
        bullets        – list[str], up to 4 tailored bullets
        keywords_to_add – list of keywords missing from profile but in JD
        note           – fallback message if LLM unavailable
    """
    profile = data.get("profile") or {}
    job     = data.get("job") or {}

    title   = job.get("title", "the role")
    company = job.get("company", "the company")
    desc    = (job.get("description") or "").lower()
    skills  = [s.lower() for s in (profile.get("skills") or [])]

    # Keyword gap analysis (always works, no API)
    SC_VOCAB = [
        "supply chain", "logistics", "procurement", "sap", "erp", "excel",
        "forecasting", "demand planning", "inventory", "operations",
        "warehouse", "transport", "s&op", "mrp", "wms", "freight",
        "customs", "incoterms", "purchasing", "vendor management",
        "power bi", "sql", "data analysis", "stakeholder management",
    ]
    missing_kw = [kw for kw in SC_VOCAB if kw in desc and kw not in " ".join(skills)]

    # Try LLM
    try:
        from backend.services.automation_runtime import _llm
        name       = profile.get("candidate_name") or "the candidate"
        skills_str = ", ".join((profile.get("skills") or [])[:8])
        exp        = profile.get("years_of_experience_hint") or "relevant"
        desc_snip  = (job.get("description") or "")[:400]
        prompt = (
            f"Tailor a resume for {name} applying to '{title}' at {company}. "
            f"Candidate skills: {skills_str}. Experience: {exp}. "
            f"Job description excerpt: {desc_snip}. "
            "Return ONLY: "
            "1) A one-line positioning headline. "
            "2) Three bullet points (start each with a strong past-tense action verb) "
            "highlighting relevant supply chain / logistics experience. "
            "3) A comma-separated list of keywords missing from the candidate profile that appear in the JD. "
            "Format strictly as:\nHEADLINE: ...\nBULLETS:\n- ...\n- ...\n- ...\nMISSING_KW: ..."
        )
        raw = _llm(prompt, max_tokens=350)
        if raw:
            lines = raw.splitlines()
            headline = ""
            bullets  = []
            kw_line  = ""
            for line in lines:
                if line.startswith("HEADLINE:"):
                    headline = line.replace("HEADLINE:", "").strip()
                elif line.startswith("- "):
                    bullets.append(line[2:].strip())
                elif line.startswith("MISSING_KW:"):
                    kw_line = line.replace("MISSING_KW:", "").strip()
            return {
                "headline":        headline,
                "bullets":         bullets[:4],
                "keywords_to_add": [k.strip() for k in kw_line.split(",") if k.strip()],
                "note":            "LLM-generated",
            }
    except Exception:
        pass

    # Offline fallback
    exp        = profile.get("years_of_experience_hint") or "relevant"
    top_skills = ", ".join((profile.get("skills") or [])[:4]) or "supply chain & logistics"
    return {
        "headline":        f"{exp} supply chain & logistics professional seeking {title} at {company}",
        "bullets": [
            f"Managed end-to-end supply chain operations using {top_skills}",
            "Analysed KPIs and inventory data to identify cost-saving opportunities",
            "Coordinated with cross-functional teams to ensure on-time delivery",
            "Maintained supplier relationships and managed procurement workflows",
        ],
        "keywords_to_add": missing_kw[:8],
        "note":            "Offline template — add an LLM key for personalised bullets",
    }
