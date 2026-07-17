"""
job_fit_service.py  — Job scoring + UK salary threshold validation

Salary threshold rules (Skilled Worker Visa, effective April 2024):
  Standard roles:        £38,700 / year  (or £15.88/hr)
  Shortage occupation:   £30,960 / year  (80% of standard)
  Health & Education:    £23,200 / year  (separate pay scales)

If a job's salary cannot be parsed or is None, we conservatively
return True (do not skip) so we don't discard unparseable listings.
"""
from __future__ import annotations

import re
from typing import Optional

# UK Skilled Worker Visa salary thresholds (£/yr)
SALARY_STANDARD   = 38_700
SALARY_SHORTAGE   = 30_960
SALARY_HEALTH_EDU = 23_200

# SOC codes that qualify for the lower health/education threshold
_HEALTH_EDU_SOC_PREFIXES = ("2211", "2217", "2231", "2311", "2314", "6141", "6143")


def salary_meets_threshold(
    salary_text: Optional[str],
    soc_code:    Optional[str] = None,
    threshold:   Optional[int] = None,
) -> bool:
    """Return True if the parsed salary meets the relevant UK visa threshold.

    Args:
        salary_text: Raw salary string from scraper, e.g. '£35,000 - £42,000 per year'
        soc_code:    Optional SOC code string to pick the right threshold tier
        threshold:   Override the threshold (e.g. pass SALARY_SHORTAGE explicitly)

    Returns:
        True  — salary is at or above threshold, OR could not be parsed (benefit of doubt)
        False — salary is explicitly below threshold
    """
    if not salary_text:
        return True  # unknown salary → don't skip

    annual = _parse_annual_salary(salary_text)
    if annual is None:
        return True  # unparseable → don't skip

    if threshold is None:
        threshold = _pick_threshold(soc_code)

    return annual >= threshold


def score_job(job: dict, profile: dict) -> int:
    """Simple keyword-overlap fit score 0–100."""
    title       = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    skills      = [s.lower() for s in (profile.get("skills") or [])]
    roles       = [r.lower() for r in (profile.get("likely_roles") or [])]

    if not skills and not roles:
        return 50  # neutral if no profile

    matches = sum(1 for s in skills if s in description or s in title)
    matches += sum(2 for r in roles  if r in title)   # title match weights double
    total    = len(skills) + len(roles) * 2
    return min(100, int(matches / max(total, 1) * 100))


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_annual_salary(text: str) -> Optional[int]:
    """Extract the lower bound of a salary range as an annual £ figure."""
    text = text.replace(",", "").replace("\u00a3", "")  # strip £ / commas
    # Match patterns like  35000, 35k, 35,000 - 42,000, £35k/yr
    numbers = re.findall(r"(\d+(?:\.\d+)?)[kK]?", text)
    parsed  = []
    for n in numbers:
        v = float(n)
        if "k" in text[text.find(n) : text.find(n) + len(n) + 1].lower():
            v *= 1000
        # Hourly rate heuristic: values < 200 are likely hourly
        if v < 200:
            v *= 37.5 * 52   # 37.5 hr/week × 52 weeks
        if 10_000 <= v <= 500_000:  # sanity range
            parsed.append(int(v))

    return min(parsed) if parsed else None   # use lower bound of range


def _pick_threshold(soc_code: Optional[str]) -> int:
    if soc_code and str(soc_code).startswith(_HEALTH_EDU_SOC_PREFIXES):
        return SALARY_HEALTH_EDU
    return SALARY_STANDARD
