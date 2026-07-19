"""backend/pipeline/scoring.py

Job matching / scoring for the rebuilt pipeline.

Two pure, independently-testable functions:

  * classify_sponsorship(description) -> "yes" | "no" | "unknown"
        Keyword classifier for UK Skilled Worker visa sponsorship signals.
  * score_job(job, profile, keywords) -> dict
        Deterministic 0-100 fit score with a short human-readable breakdown.

Both are deliberately free of network / LLM calls so they can be unit-tested in
isolation and run instantly. The LLM is an optional enrichment layer that lives
in the drafting/orchestration code, not here.
"""
from __future__ import annotations

from typing import Callable, List, Optional

# ---------------------------------------------------------------------------
# Sponsorship classifier
# ---------------------------------------------------------------------------

_SPONSOR_NEGATIVE = [
    "no sponsorship", "unable to sponsor", "must have right to work",
    "no visa sponsorship", "cannot sponsor", "not able to sponsor",
    "without sponsorship", "you must already have the right to work",
    "must already hold", "no tier 2", "must be eligible to work in the uk",
    "no work permit", "will not sponsor",
]
_SPONSOR_POSITIVE = [
    "visa sponsorship", "sponsorship available", "skilled worker visa",
    "certificate of sponsorship", "cos available", "we can sponsor",
    "eligible for sponsorship", "sponsorship may be available",
    "tier 2", "skilled worker", "sponsor a visa",
]


def classify_sponsorship(description: str) -> str:
    """Return "yes"/"no"/"unknown" for visa sponsorship based on the JD text.

    A negative signal always wins over a positive one so we never over-promise
    sponsorship on a job that explicitly rules it out.
    """
    text = (description or "").lower()
    if any(x in text for x in _SPONSOR_NEGATIVE):
        return "no"
    if any(x in text for x in _SPONSOR_POSITIVE):
        return "yes"
    return "unknown"


# ---------------------------------------------------------------------------
# Sponsorship *tier* — separates an authoritative GOV.UK register match from a
# weak, gameable JD-text mention. These must never be conflated: a job is only
# "verified" if the employer is on the official register.
# ---------------------------------------------------------------------------

SPONSOR_VERIFIED  = "verified"   # employer matched against GOV.UK sponsor register
SPONSOR_MENTIONED = "mentioned"  # JD text mentions sponsorship, employer NOT verified
SPONSOR_NONE      = "none"       # JD explicitly rules sponsorship out
SPONSOR_UNKNOWN   = "unknown"    # no signal either way


def sponsorship_tier(job: dict, sponsor_verifier: Optional[Callable[[str], bool]] = None) -> str:
    """Classify a job's sponsorship signal into a trust tier.

    ``sponsor_verifier`` is an optional callable ``company_name -> bool`` (e.g.
    ``SponsorRegister.verify``). It is injected rather than imported so this
    module stays pure/network-free and unit-testable.

    An explicit "no sponsorship" in the JD always wins so we never over-promise.
    Otherwise a register match yields ``verified``; a JD-only mention yields the
    clearly-weaker ``mentioned``; anything else is ``unknown``.
    """
    desc_class = classify_sponsorship(job.get("description", ""))
    if desc_class == "no":
        return SPONSOR_NONE
    company = (job.get("company") or "").strip()
    if sponsor_verifier is not None and company:
        try:
            if sponsor_verifier(company):
                return SPONSOR_VERIFIED
        except Exception:
            pass
    if desc_class == "yes":
        return SPONSOR_MENTIONED
    return SPONSOR_UNKNOWN


# ---------------------------------------------------------------------------
# Fit scoring
# ---------------------------------------------------------------------------

ENTRY_LEVEL_TITLES = [
    "graduate", "junior", "entry level", "entry-level", "trainee",
    "assistant", "associate", "coordinator", "analyst", "apprentice",
]

SENIOR_TERMS = ["senior", "lead", "head of", "director", "principal", "vp ", "manager"]


def _core_terms(profile: Optional[dict], keywords: List[str]) -> List[str]:
    """The candidate's own domain vocabulary — derived 100% from the parsed
    resume (skills + likely roles) and the keywords the user actually chose,
    never a hardcoded industry. This is what the domain bonus / title-floor
    reward, so scoring reflects THIS candidate rather than a baked-in persona.
    """
    terms = set()
    for src in ((profile or {}).get("skills") or [], (profile or {}).get("likely_roles") or []):
        for item in src:
            item = (item or "").strip().lower()
            if len(item) >= 2:
                terms.add(item)
    for kw in keywords or []:
        kw = (kw or "").strip().lower()
        if len(kw) >= 2:
            terms.add(kw)
    return list(terms)


def score_job(job: dict, profile: Optional[dict], keywords: List[str]) -> dict:
    """Score a job 0-100 for a candidate.

    Returns ``{"fit_score", "fit_level", "reasons", "gaps"}``.

    Rules — every signal is derived from the candidate (parsed resume skills/
    roles + the keywords they chose), with NO hardcoded industry:
      * Keyword overlap with the search keywords (title-only when the JD is
        short, which LinkedIn/Adzuna teasers often are).
      * Bonus when the job matches the candidate's own skill/role vocabulary.
      * A title matching one of the candidate's core terms earns a guaranteed
        floor of 15 so strong-title/short-description jobs are never buried.
      * Bonus for entry-level titles and explicit sponsorship.
      * Penalty for senior titles when the candidate has no numeric experience.
    """
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    combined = f"{title} {desc}"
    desc_is_short = len(desc.strip()) < 80

    reasons: List[str] = []

    target = title if desc_is_short else combined
    kw_hits = sum(1 for kw in keywords if kw and kw.strip().lower() in target)
    kw_score = min(int(kw_hits / max(len(keywords), 1) * 60), 60)
    if kw_hits:
        reasons.append(f"{kw_hits} keyword match(es)")

    core_terms = _core_terms(profile, keywords)
    core_hits = sum(1 for t in core_terms if t in title) + (
        sum(1 for t in core_terms if t in desc) if not desc_is_short else 0
    )
    core_bonus = min(core_hits * 3, 20)
    if core_hits:
        reasons.append("matches your background")

    title_core_match = any(t in title for t in core_terms)
    title_floor = 15 if title_core_match else 0

    entry_bonus = 15 if any(t in title for t in ENTRY_LEVEL_TITLES) else 0
    if entry_bonus:
        reasons.append("entry-level title")

    spons_bonus = 10 if job.get("sponsorship_status") == "yes" else 0
    if spons_bonus:
        reasons.append("sponsorship stated")

    exp_hint = (profile or {}).get("years_of_experience_hint") or ""
    has_experience = any(c.isdigit() for c in exp_hint)
    senior_penalty = -20 if any(t in title for t in SENIOR_TERMS) and not has_experience else 0
    if senior_penalty:
        reasons.append("senior title vs limited experience")

    score = max(
        title_floor,
        min(kw_score + core_bonus + entry_bonus + spons_bonus + senior_penalty, 100),
    )
    score = max(0, score)
    level = "strong" if score >= 60 else ("moderate" if score >= 30 else "weak")

    # Skill gaps: vocabulary terms the JD requires that the resume does not list.
    # Sourced from the parser's cross-domain skills bank, not a fixed industry.
    gaps: List[str] = []
    resume_skills = {s.lower() for s in (profile or {}).get("skills", [])}
    try:
        from backend.services.parser.resume_parser import SKILLS_BANK as _BANK
    except Exception:
        _BANK = ["sap", "excel", "forecasting", "erp", "sql", "python"]
    for term in _BANK:
        if term in desc and term not in resume_skills and term not in gaps:
            gaps.append(term)
        if len(gaps) >= 6:
            break

    return {"fit_score": score, "fit_level": level, "reasons": reasons, "gaps": gaps}
