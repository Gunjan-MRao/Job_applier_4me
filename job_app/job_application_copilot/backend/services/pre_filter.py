"""
pre_filter.py  — Zero-cost local pre-filter for UK Visa Sponsorship job search

Runs BEFORE any LLM call to discard obviously unsuitable jobs instantly.
Saves Groq API tokens and speeds up the pipeline significantly.

Filtering layers (in order of cost, cheapest first):
  1. Hard disqualifiers   — regex on title+description (immediate SKIP)
  2. Seniority guard      — skip roles clearly too senior
  3. UK visa signals      — boost / flag based on positive/negative sponsor cues
  4. Salary pre-check     — discard jobs explicitly below UK visa threshold

Usage:
    from backend.services.pre_filter import should_process_job, FilterResult

    result = should_process_job(job, profile)
    if not result.should_process:
        print(f"Skipped: {result.reason}")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration — edit here or override via config.yaml
# ---------------------------------------------------------------------------

# Jobs containing ANY of these phrases (case-insensitive) are hard-discarded.
# These are split into categories for clarity.
_HARD_DISQUALIFIERS: list[str] = [
    # Visa/citizenship bars
    r"no sponsorship",
    r"no visa sponsorship",
    r"must be (a )?(uk )?citizen",
    r"uk citizens? only",
    r"british citizens? only",
    r"must have (the )?right to work",
    r"right to work (?:in the uk )?required",
    r"no tier ?2",
    r"cannot sponsor",
    r"unable to (offer|provide) sponsorship",
    r"sponsorship (is )?not (available|offered|provided)",
    r"applicants? must already have.*right to work",
    # Security clearance (usually citizenship-linked)
    r"security clearance required",
    r"sc cleared",
    r"dv cleared",
    r"nv1 cleared",
    r"active security clearance",
    r"must hold.*clearance",
    # US / non-UK geography
    r"us citizens? only",
    r"green card",
    r"authorized? to work in the (us|usa|united states)",
    # Explicit exclusions for work authorisation
    r"no opt\b",
    r"no cpt\b",
    r"no h[\-]?1b",
]

# Roles with these seniority words in the TITLE are skipped (configurable).
_SENIORITY_SKIP_TITLE: list[str] = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\bprincipal\b",
    r"\blead\b",
    r"\bstaff\b",
    r"\bdirector\b",
    r"\bvp\b",
    r"\bvice president\b",
    r"\bchief\b",
    r"\bhead of\b",
    r"\bmanager\b",    # remove this line if your profile targets management
]

# Positive sponsorship signals in job text — not required but logged.
_POSITIVE_SPONSOR_SIGNALS: list[str] = [
    r"skilled worker visa",
    r"tier ?2",
    r"visa sponsorship (available|provided|offered|considered|welcome)",
    r"we (can|will) (consider )?sponsor",
    r"certificate of sponsorship",
    r"cos\b",
    r"happy to sponsor",
]

# UK salary threshold for Skilled Worker Visa (standard track, April 2024)
_MIN_SALARY_GBP = 38_700


# ---------------------------------------------------------------------------
# Public data class
# ---------------------------------------------------------------------------

@dataclass
class FilterResult:
    should_process: bool
    reason: str
    sponsor_signal: str          = "unknown"   # "positive", "negative", "unknown"
    seniority_flag: bool         = False
    salary_ok: bool              = True
    matched_disqualifiers: list  = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def should_process_job(
    job: dict,
    profile: Optional[dict] = None,
    skip_senior: bool = True,
    min_salary: int = _MIN_SALARY_GBP,
) -> FilterResult:
    """
    Run all pre-filter layers and return a FilterResult.

    Args:
        job:          Job dict with keys: title, description, salary,
                      sponsorship_status, company
        profile:      Optional resume profile (used for future skill-gap pre-filter)
        skip_senior:  If True, skip seniority-flagged titles
        min_salary:   Annual GBP threshold; set 0 to disable salary check

    Returns:
        FilterResult.should_process = False  →  discard this job
        FilterResult.should_process = True   →  proceed to LLM scoring
    """
    title       = (job.get("title") or "").lower().strip()
    description = (job.get("description") or "").lower()
    salary_raw  = (job.get("salary") or "").lower()
    combined    = f"{title} {description}"

    # ── Layer 1: Hard disqualifiers ─────────────────────────────────────
    matched = [p for p in _HARD_DISQUALIFIERS if re.search(p, combined, re.I)]
    if matched:
        return FilterResult(
            should_process=False,
            reason=f"Hard disqualifier matched: '{matched[0]}'",
            sponsor_signal="negative",
            matched_disqualifiers=matched,
        )

    # ── Layer 2: Seniority guard ────────────────────────────────────────
    seniority_flag = bool(
        any(re.search(p, title, re.I) for p in _SENIORITY_SKIP_TITLE)
    )
    if skip_senior and seniority_flag:
        return FilterResult(
            should_process=False,
            reason=f"Seniority guard: title '{job.get('title', '')}' appears too senior",
            seniority_flag=True,
        )

    # ── Layer 3: Sponsorship signal ─────────────────────────────────────
    has_positive = any(
        re.search(p, combined, re.I) for p in _POSITIVE_SPONSOR_SIGNALS
    )
    # Also check the structured sponsorship_status field from the scraper
    structured_status = (job.get("sponsorship_status") or "").lower()
    if structured_status == "no":
        return FilterResult(
            should_process=False,
            reason="Structured sponsorship_status field = 'no'",
            sponsor_signal="negative",
        )
    sponsor_signal = "positive" if (has_positive or structured_status == "yes") else "unknown"

    # ── Layer 4: Salary pre-check ───────────────────────────────────────
    salary_ok = True
    if min_salary > 0 and salary_raw:
        parsed = _quick_parse_salary(salary_raw)
        if parsed is not None and parsed < min_salary:
            salary_ok = False
            return FilterResult(
                should_process=False,
                reason=f"Salary {parsed:,} GBP < UK visa threshold {min_salary:,} GBP",
                sponsor_signal=sponsor_signal,
                seniority_flag=seniority_flag,
                salary_ok=False,
            )

    # ── All layers passed ───────────────────────────────────────────────
    return FilterResult(
        should_process=True,
        reason="Passed all pre-filters",
        sponsor_signal=sponsor_signal,
        seniority_flag=seniority_flag,
        salary_ok=salary_ok,
    )


def is_company_blacklisted(company: str, blacklist: list[str]) -> bool:
    """
    Check if a company name is in the blacklist.
    Matching is case-insensitive substring match.

    Args:
        company:   Company name string from job listing
        blacklist: List of strings to block (e.g. ["Hays", "Adecco", "Reed"])

    Returns:
        True if the company should be skipped
    """
    if not company or not blacklist:
        return False
    co_lower = company.lower().strip()
    return any(bl.lower().strip() in co_lower or co_lower in bl.lower().strip()
               for bl in blacklist)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _quick_parse_salary(text: str) -> Optional[int]:
    """
    Lightweight salary parser — extract lowest bound as annual GBP.
    Returns None if unparseable (benefit of the doubt → don't skip).
    """
    text = text.replace(",", "").replace("£", "").replace("\u00a3", "")
    numbers = re.findall(r"(\d+(?:\.\d+)?)(k?)", text, re.I)
    parsed = []
    for num, suffix in numbers:
        v = float(num)
        if suffix.lower() == "k":
            v *= 1000
        # Hourly heuristic: < 500 is almost certainly hourly
        if v < 500:
            v = v * 37.5 * 52
        if 10_000 <= v <= 500_000:
            parsed.append(int(v))
    return min(parsed) if parsed else None
