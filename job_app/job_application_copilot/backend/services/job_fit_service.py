"""
job_fit_service.py  — Job scoring + UK salary threshold validation

v2 — wired into Phase 1 of the zero-cost refactor:
  * score_job()          — fast local keyword overlap (unchanged, used as fallback)
  * score_job_full()     — NEW: runs pre_filter first, then Groq LLM scoring
  * salary_meets_threshold() — unchanged

Salary threshold rules (Skilled Worker Visa, effective April 2024):
  Standard roles:        £38,700 / year  (or £15.88/hr)
  Shortage occupation:   £30,960 / year  (80% of standard)
  Health & Education:    £23,200 / year  (separate pay scales)

If a job's salary cannot be parsed or is None, we conservatively
return True (do not skip) so we don't discard unparseable listings.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# UK Skilled Worker Visa salary thresholds (£/yr)
SALARY_STANDARD   = 38_700
SALARY_SHORTAGE   = 30_960
SALARY_HEALTH_EDU = 23_200

_HEALTH_EDU_SOC_PREFIXES = ("2211", "2217", "2231", "2311", "2314", "6141", "6143")


# ---------------------------------------------------------------------------
# Full pipeline: pre-filter → Groq LLM  (Phase 1 entry point)
# ---------------------------------------------------------------------------

def score_job_full(
    job: dict,
    profile: dict,
    blacklist: Optional[list[str]] = None,
    skip_senior: bool = True,
    use_llm: bool = True,
) -> dict:
    """
    Full scoring pipeline:
      1. Blacklist check  (instant)
      2. Pre-filter       (instant regex/string, no API)
      3. Groq LLM scoring (free API, ~0.5s)

    Returns the Groq assessment dict (same shape as groq_llm_service.score_job_with_llm)
    with an extra 'filter_result' key attached.

    If pre-filter discards the job, returns immediately with fit_score=0
    and recommendation='SKIP' without touching the Groq API.
    """
    from backend.services.pre_filter import is_company_blacklisted, should_process_job

    # Step 1 — Blacklist
    company = job.get("company") or ""
    if blacklist and is_company_blacklisted(company, blacklist):
        return {
            "fit_score":          0,
            "sponsor_confidence": 0,
            "recommendation":     "SKIP",
            "key_matches":        [],
            "missing_skills":     [],
            "reasoning":          f"Company '{company}' is on the blacklist.",
            "filter_result":      {"should_process": False, "reason": "blacklisted"},
        }

    # Step 2 — Pre-filter
    f_result = should_process_job(job, profile, skip_senior=skip_senior)
    if not f_result.should_process:
        logger.debug("Pre-filter skipped '%s' @ %s: %s",
                     job.get("title"), company, f_result.reason)
        return {
            "fit_score":          0,
            "sponsor_confidence": 0,
            "recommendation":     "SKIP",
            "key_matches":        [],
            "missing_skills":     [],
            "reasoning":          f_result.reason,
            "filter_result":      {
                "should_process":       False,
                "reason":               f_result.reason,
                "sponsor_signal":       f_result.sponsor_signal,
                "matched_disqualifiers": f_result.matched_disqualifiers,
            },
        }

    # Step 3 — LLM scoring (Groq, with local fallback)
    if use_llm:
        try:
            from backend.services.groq_llm_service import score_job_with_llm
            result = score_job_with_llm(job, profile)
        except Exception as exc:
            logger.warning("Groq scoring failed (%s) — using local score", exc)
            result = _local_result(job, profile)
    else:
        result = _local_result(job, profile)

    result["filter_result"] = {
        "should_process": True,
        "reason":         f_result.reason,
        "sponsor_signal": f_result.sponsor_signal,
    }
    return result


# ---------------------------------------------------------------------------
# Original lightweight scorer (kept as fallback & for fast list-view scores)
# ---------------------------------------------------------------------------

def score_job(job: dict, profile: dict) -> int:
    """Simple keyword-overlap fit score 0–100 (no API, instant)."""
    title       = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    skills      = [s.lower() for s in (profile.get("skills") or [])]
    roles       = [r.lower() for r in (profile.get("likely_roles") or [])]

    if not skills and not roles:
        return 50

    matches  = sum(1 for s in skills if s in description or s in title)
    matches += sum(2 for r in roles  if r in title)
    total    = len(skills) + len(roles) * 2
    return min(100, int(matches / max(total, 1) * 100))


# ---------------------------------------------------------------------------
# Salary threshold helpers (unchanged from v1)
# ---------------------------------------------------------------------------

def salary_meets_threshold(
    salary_text: Optional[str],
    soc_code:    Optional[str] = None,
    threshold:   Optional[int] = None,
) -> bool:
    if not salary_text:
        return True
    annual = _parse_annual_salary(salary_text)
    if annual is None:
        return True
    if threshold is None:
        threshold = _pick_threshold(soc_code)
    return annual >= threshold


def _parse_annual_salary(text: str) -> Optional[int]:
    text    = text.replace(",", "").replace("\u00a3", "")
    numbers = re.findall(r"(\d+(?:\.\d+)?)[kK]?", text)
    parsed  = []
    for n in numbers:
        v = float(n)
        if "k" in text[text.find(n): text.find(n) + len(n) + 1].lower():
            v *= 1000
        if v < 200:
            v *= 37.5 * 52
        if 10_000 <= v <= 500_000:
            parsed.append(int(v))
    return min(parsed) if parsed else None


def _pick_threshold(soc_code: Optional[str]) -> int:
    if soc_code and str(soc_code).startswith(_HEALTH_EDU_SOC_PREFIXES):
        return SALARY_HEALTH_EDU
    return SALARY_STANDARD


def _local_result(job: dict, profile: dict) -> dict:
    score = score_job(job, profile)
    return {
        "fit_score":          score,
        "sponsor_confidence": 50,
        "recommendation":     "APPLY" if score >= 70 else "INVESTIGATE" if score >= 40 else "SKIP",
        "key_matches":        [],
        "missing_skills":     [],
        "reasoning":          "Local keyword score (Groq not used).",
    }
