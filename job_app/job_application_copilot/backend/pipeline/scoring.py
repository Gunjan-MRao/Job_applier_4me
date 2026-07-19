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

from typing import List, Optional

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
# Fit scoring
# ---------------------------------------------------------------------------

ENTRY_LEVEL_TITLES = [
    "graduate", "junior", "entry level", "entry-level", "trainee",
    "assistant", "associate", "coordinator", "analyst", "apprentice",
]

SC_CORE_TERMS = [
    "supply chain", "logistics", "procurement", "operations",
    "warehouse", "transport", "inventory", "demand plan", "forecasting",
    "s&op", "purchasing", "vendor", "freight", "distribution",
    "sap", "erp", "excel",
]

SENIOR_TERMS = ["senior", "lead", "head of", "director", "principal", "vp ", "manager"]


def score_job(job: dict, profile: Optional[dict], keywords: List[str]) -> dict:
    """Score a job 0-100 for a candidate.

    Returns ``{"fit_score", "fit_level", "reasons", "gaps"}``.

    Rules (kept identical to the field-proven original scorer so results are
    stable across the app):
      * Keyword overlap with the search keywords (title-only when the JD is
        short, which LinkedIn/Adzuna teasers often are).
      * Bonus for supply-chain core terms, entry-level titles and explicit
        sponsorship.
      * A title containing a supply-chain term earns a guaranteed floor of 15 so
        strong-title/short-description jobs are never buried.
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

    sc_hits = sum(1 for t in SC_CORE_TERMS if t in title) + (
        sum(1 for t in SC_CORE_TERMS if t in desc) if not desc_is_short else 0
    )
    sc_bonus = min(sc_hits * 3, 20)
    if sc_hits:
        reasons.append("supply-chain terms present")

    title_sc_match = any(t in title for t in SC_CORE_TERMS)
    title_floor = 15 if title_sc_match else 0

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
        min(kw_score + sc_bonus + entry_bonus + spons_bonus + senior_penalty, 100),
    )
    score = max(0, score)
    level = "strong" if score >= 60 else ("moderate" if score >= 30 else "weak")

    gaps: List[str] = []
    resume_skills = {s.lower() for s in (profile or {}).get("skills", [])}
    for term in ("sap", "excel", "forecasting", "erp"):
        if term in desc and term not in resume_skills:
            gaps.append(term)

    return {"fit_score": score, "fit_level": level, "reasons": reasons, "gaps": gaps}
