"""backend/pipeline/drafting.py

Cover-letter and cold-email drafting for the rebuilt pipeline.

The LLM is injected as a callable (``llm_fn(prompt, max_tokens) -> str | None``)
so this module is trivially unit-testable with a stub and has ZERO hard
dependency on any provider. When ``llm_fn`` is None or returns falsy, a
deterministic offline template is used instead — so drafting always produces
output, even with no API keys (the project's free-tier guarantee).

Visa-sponsorship framing follows the project's evidence-based rule: lead with
value, disclose the Certificate-of-Sponsorship need factually in the final
paragraph (never apologetically), and omit it entirely when the employer has
explicitly said they cannot sponsor.
"""
from __future__ import annotations

from typing import Callable, Optional

LLMFn = Callable[..., Optional[str]]

_SC_SKILLS = (
    "supply chain", "logistics", "procurement", "sap", "excel",
    "forecasting", "demand planning", "inventory management",
    "operations", "erp", "power bi", "sql", "s&op",
)


def _top_skills(profile: dict, pool: tuple = _SC_SKILLS, n: int = 3) -> str:
    skills = profile.get("skills") or []
    sc = [s for s in skills if s in pool]
    picked = (sc or skills)[:n]
    return ", ".join(picked) or "my skills"


# ---------------------------------------------------------------------------
# Offline templates (no API key required)
# ---------------------------------------------------------------------------

def offline_cover_letter(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    exp = profile.get("years_of_experience_hint") or "relevant"
    roles = profile.get("likely_roles") or []
    spons = job.get("sponsorship_status", "unknown")
    role_bg = roles[0].title() if roles else "supply chain and logistics"
    top_skills = _top_skills(profile)

    desc = (job.get("description") or "").lower()
    if "sap" in desc:
        detail = "I have hands-on experience with SAP which I understand is central to this role."
    elif "excel" in desc or "spreadsheet" in desc:
        detail = "I am proficient in Excel and comfortable building models and dashboards from scratch."
    elif "forecasting" in desc or "demand" in desc:
        detail = ("I have worked on demand forecasting and inventory optimisation, and I am "
                  "confident I can contribute quickly.")
    else:
        detail = ("I am confident my background in supply chain and logistics aligns well with "
                  "what you are looking for.")

    if spons == "no":
        spons_para = ""
    elif spons == "yes":
        spons_para = (
            f"\n\nOne practical note: I would require a Certificate of Sponsorship under the "
            f"Skilled Worker route. I have noted that {company} holds a sponsor licence and am "
            f"fully prepared to support the compliance process — this is straightforward from "
            f"the candidate side and I am happy to discuss it."
        )
    else:
        spons_para = (
            f"\n\nOne practical note: I would require a Certificate of Sponsorship under the "
            f"Skilled Worker route. I would welcome the chance to discuss whether {company} is "
            f"able to support this — I am prepared to make the process as simple as possible."
        )

    return (
        f"Dear Hiring Team at {company},\n\n"
        f"The {title} role at {company} is exactly the kind of position I have been working towards.\n\n"
        f"My background in {role_bg} has given me {exp} of hands-on experience with "
        f"{top_skills}. {detail}\n\n"
        f"I am ready to contribute from day one and would welcome the chance to discuss how "
        f"I can add value — would you be open to a brief call this week?"
        f"{spons_para}\n\n"
        f"Thank you for your consideration.\n\nKind regards,\n{name}"
    )


def offline_cold_email(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    exp = profile.get("years_of_experience_hint") or "relevant"
    spons = job.get("sponsorship_status", "unknown")
    top_skills = _top_skills(profile, n=3)

    spons_line = "" if spons == "no" else (
        "\n\nNote: I require a Certificate of Sponsorship (Skilled Worker route) — "
        "happy to discuss this on a call."
    )

    return (
        f"Subject: {title} — {name}\n\n"
        f"Hi,\n\n"
        f"I came across the {title} role at {company} and wanted to reach out directly.\n\n"
        f"I have {exp} experience in {top_skills} and am actively looking for a "
        f"supply chain or logistics role in the UK. "
        f"I am a quick learner, detail-oriented, and ready to contribute from day one."
        f"{spons_line}\n\n"
        f"Would you have 15 minutes for a quick chat?\n\nBest,\n{name}"
    )


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _sponsorship_instruction(name: str, company: str, spons: str, email: bool = False) -> str:
    if spons == "no":
        return "Do NOT mention visa sponsorship — this employer cannot sponsor."
    if email:
        return (
            "IMPORTANT: Add a single final line disclosing that the candidate requires a "
            "Certificate of Sponsorship (Skilled Worker route). Keep it brief, factual, and "
            "confident — NOT apologetic."
        )
    if spons == "yes":
        return (
            f"IMPORTANT: In the FINAL paragraph add exactly 1-2 sentences disclosing that "
            f"{name} requires a Certificate of Sponsorship (Skilled Worker route), and that "
            f"they have noted {company} holds a sponsor licence and are prepared to support the "
            f"compliance process. Frame as logistics, NOT a request. Confident tone."
        )
    return (
        f"IMPORTANT: In the FINAL paragraph add exactly 1-2 sentences disclosing that {name} "
        f"requires a Certificate of Sponsorship (Skilled Worker route), and would welcome the "
        f"chance to discuss whether {company} is able to support this. Frame as logistics, NOT a "
        f"request. Confident tone."
    )


def cover_letter_prompt(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    spons = job.get("sponsorship_status", "unknown")
    skills_str = ", ".join((profile.get("skills") or [])[:6]) or "supply chain and logistics"
    exp = profile.get("years_of_experience_hint") or "some"
    desc_snip = (job.get("description") or "")[:400]
    return (
        f"Write a concise, genuine cover letter for {name} applying for '{title}' at {company}. "
        f"The candidate has {exp} experience in supply chain and logistics with skills: {skills_str}. "
        f"Job excerpt: {desc_snip}. "
        f"Structure: (1) Opening — specific interest in role + company, (2) Value — strongest "
        f"qualification matched to JD, (3) Evidence — one specific quantified achievement, "
        f"(4) Sponsorship disclosure paragraph. "
        f"Rules: under 230 words, warm human tone, no filler openers like 'I am writing to', "
        f"no square brackets, first sentence names role + company, end paragraph 3 with a direct "
        f"ask for a call. "
        f"{_sponsorship_instruction(name, company, spons)}"
    )


def cold_email_prompt(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    spons = job.get("sponsorship_status", "unknown")
    skills_str = ", ".join((profile.get("skills") or [])[:4]) or "supply chain"
    exp = profile.get("years_of_experience_hint") or "some"
    return (
        f"Write a short cold email from {name} to a recruiter at {company} about '{title}'. "
        f"Background: {exp} experience in supply chain / logistics, skills: {skills_str}. "
        f"Rules: subject line first starting 'Subject:', under 130 words total, sound human not "
        f"corporate, no hollow openers, end with a low-friction ask for a 15-minute call. "
        f"{_sponsorship_instruction(name, company, spons, email=True)}"
    )


# ---------------------------------------------------------------------------
# Public drafting API
# ---------------------------------------------------------------------------

def draft_cover_letter(profile: dict, job: dict, llm_fn: Optional[LLMFn] = None) -> str:
    """Return a tailored cover letter, using ``llm_fn`` when it yields text and
    falling back to the offline template otherwise."""
    if llm_fn is not None:
        try:
            out = llm_fn(cover_letter_prompt(profile, job), max_tokens=450)
        except Exception:
            out = None
        if out and out.strip():
            return out.strip()
    return offline_cover_letter(profile, job)


def draft_cold_email(profile: dict, job: dict, llm_fn: Optional[LLMFn] = None) -> str:
    """Return a short cold recruiter email, LLM-first with offline fallback."""
    if llm_fn is not None:
        try:
            out = llm_fn(cold_email_prompt(profile, job), max_tokens=300)
        except Exception:
            out = None
        if out and out.strip():
            return out.strip()
    return offline_cold_email(profile, job)
