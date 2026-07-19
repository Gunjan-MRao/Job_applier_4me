"""backend/pipeline/orchestrator.py

The rebuilt core pipeline, wired together:

    resume profile + preferences
        -> gather_jobs()   (Adzuna primary -> Reed -> scraper -> mock)
        -> score each job  (scoring.score_job)
        -> draft top jobs  (drafting.draft_cover_letter / draft_cold_email)
        -> ranked results

Everything is plain functions with explicit inputs/outputs so each stage is
importable and testable on its own. `gather_jobs` picks the best AVAILABLE
source in priority order and always returns something (mock listings as the
last resort) so the UI can demo the whole flow with zero API keys.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from backend.pipeline import job_sources, scoring, drafting

logger = logging.getLogger(__name__)


def _dedupe(jobs: List[dict]) -> List[dict]:
    seen, out = set(), []
    for j in jobs:
        key = ((j.get("title") or "").strip().lower(), (j.get("company") or "").strip().lower())
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


def gather_jobs(
    keywords: List[str],
    location: str = "United Kingdom",
    allow_scraper_fallback: bool = False,
    log_fn: Optional[Callable] = None,
    sponsor_verifier: Optional[Callable[[str], bool]] = None,
) -> dict:
    """Fetch jobs from the best available source, in priority order.

    Returns a dict::

        {
          "jobs":        [ ...canonical job dicts, sponsorship classified... ],
          "source_used": "Adzuna" | "Reed" | "scraper" | "mock",
          "used_mock":   bool,
          "notes":       [ human-readable status strings for the run log ],
        }

    Priority: Adzuna (primary) -> Reed (secondary) -> legacy scraper (opt-in
    fallback) -> mock listings (always). The first source that returns any jobs
    wins; live sources are then merged so a configured Reed key can top up
    Adzuna results.
    """
    # Each keyword is a separate role phrase (e.g. "logistics coordinator"), so
    # query the APIs once PER keyword and merge. Joining them into one string
    # makes Adzuna/Reed require ALL words in a single listing, which returns
    # zero results for realistic multi-role searches — the classic silent
    # "0 real jobs" failure. A single fallback query keeps the flow working when
    # no keywords are supplied.
    queries = [k.strip() for k in (keywords or [])[:3] if k and k.strip()]
    if not queries:
        # No keywords supplied — use a neutral, non-persona default so the flow
        # still returns something. Real searches always pass resume-derived
        # keywords; this only guards the empty-input edge case.
        queries = ["jobs"]
    notes: List[str] = []
    jobs: List[dict] = []
    source_used = "mock"

    # 1. Adzuna (primary)
    adz: List[dict] = []
    for q in queries:
        adz.extend(job_sources.fetch_adzuna(q, location))
    if adz:
        jobs.extend(adz)
        source_used = "Adzuna"
        notes.append(f"Adzuna returned {len(adz)} jobs")
    else:
        notes.append("Adzuna unavailable (no key or no results)")

    # 2. Reed (secondary — merged on top of Adzuna if configured)
    reed: List[dict] = []
    for q in queries:
        reed.extend(job_sources.fetch_reed(q, location))
    if reed:
        jobs.extend(reed)
        if source_used == "mock":
            source_used = "Reed"
        notes.append(f"Reed returned {len(reed)} jobs")
    else:
        notes.append("Reed unavailable (no key or no results)")

    # 3. Legacy scraper (opt-in, unreliable)
    if not jobs and allow_scraper_fallback:
        scraped = job_sources.fetch_scraper_fallback(keywords, location, log_fn)
        if scraped:
            jobs.extend(scraped)
            source_used = "scraper"
            notes.append(f"Scraper fallback returned {len(scraped)} jobs (unreliable source)")
        else:
            notes.append("Scraper fallback returned nothing")

    # 4. Mock (last resort so the flow is always demoable)
    used_mock = False
    if not jobs:
        jobs = job_sources.mock_jobs()
        source_used = "mock"
        used_mock = True
        notes.append(
            "No live job source configured — using mock listings. "
            "Set ADZUNA_APP_ID / ADZUNA_APP_KEY (and optionally REED_API_KEY) for real UK data."
        )

    jobs = _dedupe(jobs)
    for j in jobs:
        j.setdefault("sponsorship_status", scoring.classify_sponsorship(j.get("description", "")))
        j["sponsor_tier"] = scoring.sponsorship_tier(j, sponsor_verifier)

    return {"jobs": jobs, "source_used": source_used, "used_mock": used_mock, "notes": notes}


def run_pipeline(
    profile: dict,
    keywords: List[str],
    location: str = "United Kingdom",
    min_fit_score: int = 10,
    draft_top_n: int = 10,
    exclude_no_sponsorship: bool = True,
    allow_scraper_fallback: bool = False,
    llm_fn: Optional[drafting.LLMFn] = None,
    log_fn: Optional[Callable] = None,
    sponsor_verifier: Optional[Callable[[str], bool]] = None,
) -> dict:
    """Run the full flow end-to-end and return ranked, drafted results.

    Returns::

        {
          "source_used", "used_mock", "notes",
          "jobs_scanned", "jobs_matched",
          "matches": [ { job fields..., "fit_score", "fit_level",
                          "cover_letter", "cold_email" }, ... ],
        }

    Drafting (LLM or offline template) is only run for the top ``draft_top_n``
    matches to keep a run fast and within free LLM rate limits.
    """
    gathered = gather_jobs(keywords, location, allow_scraper_fallback, log_fn, sponsor_verifier)
    jobs = gathered["jobs"]

    scored: List[dict] = []
    for job in jobs:
        result = scoring.score_job(job, profile, keywords)
        job = {**job, "fit_score": result["fit_score"], "fit_level": result["fit_level"],
               "score_reasons": result["reasons"], "skill_gaps": result["gaps"]}
        if job["fit_score"] < min_fit_score:
            continue
        if exclude_no_sponsorship and job.get("sponsorship_status") == "no":
            continue
        scored.append(job)

    scored.sort(key=lambda j: j["fit_score"], reverse=True)

    for job in scored[:draft_top_n]:
        job["cover_letter"] = drafting.draft_cover_letter(profile, job, llm_fn)
        job["cold_email"] = drafting.draft_cold_email(profile, job, llm_fn)

    return {
        "source_used": gathered["source_used"],
        "used_mock": gathered["used_mock"],
        "notes": gathered["notes"],
        "jobs_scanned": len(jobs),
        "jobs_matched": len(scored),
        "matches": scored,
    }
