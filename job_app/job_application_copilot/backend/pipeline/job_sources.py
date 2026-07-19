"""backend/pipeline/job_sources.py

Job-data sources for the rebuilt core pipeline.

Design decision (why this module exists):
    The original pipeline used LinkedIn/Indeed scraping (python-jobspy) plus a
    stack of HTML board scrapers as its PRIMARY job source. Those silently break
    the moment a site changes its markup or rate-limits/CAPTCHAs an automated
    client -- the classic "0 real jobs, always" failure the user hit. Scraping
    is kept only as a clearly-labelled, best-effort FALLBACK.

    The primary source is now the Adzuna Job Search API (official, free tier,
    UK-focused, plain JSON REST) with Reed.co.uk's official API as a secondary.
    Both are documented, stable contracts -- no anti-bot risk.

Priority order used by the orchestrator:
    1. Adzuna API          (primary   -- needs ADZUNA_APP_ID / ADZUNA_APP_KEY)
    2. Reed API            (secondary -- needs REED_API_KEY)
    3. Legacy HTML scraper (fallback  -- unreliable, off by default)
    4. Mock listings       (last resort so the whole flow is always demoable)

Every source returns a list of dicts in ONE canonical shape (see `make_job`),
so scoring / drafting downstream never has to care where a job came from.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, List, Optional

import requests

from backend.core.config import settings

logger = logging.getLogger(__name__)

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/gb/search"
REED_BASE = "https://www.reed.co.uk/api/1.0/search"
_HTTP_TIMEOUT = (5, 25)  # (connect, read) seconds


# ---------------------------------------------------------------------------
# Canonical job shape
# ---------------------------------------------------------------------------

def make_job(
    title: str,
    company: str,
    location: str,
    salary: str,
    url: str,
    description: str,
    source: str,
    recruiter_email: Optional[str] = None,
    date_posted: str = "",
) -> Optional[dict]:
    """Build a canonical job dict. Returns None if the title is empty.

    Sponsorship classification is deliberately left to the scoring layer so this
    module stays a pure data-fetch concern.
    """
    if not title or not str(title).strip():
        return None

    def _clean(val) -> str:
        if val is None:
            return ""
        s = str(val).strip()
        return "" if s.lower() in ("nan", "none", "n/a", "-") else s

    return {
        "title": _clean(title),
        "company": _clean(company) or "Unknown",
        "location": _clean(location) or "United Kingdom",
        "salary": _clean(salary),
        "url": url or "",
        "description": _clean(description),
        "source": source,
        "recruiter_email": recruiter_email,
        "date_posted": _clean(date_posted) or datetime.utcnow().isoformat()[:10],
    }


def _format_salary(smin, smax) -> str:
    """Render Adzuna/Reed numeric salary bounds as a readable GBP range."""
    try:
        smin = int(float(smin)) if smin else 0
        smax = int(float(smax)) if smax else 0
    except (TypeError, ValueError):
        return ""
    if smin and smax and smax != smin:
        return f"£{smin:,}–£{smax:,}"
    if smin:
        return f"£{smin:,}"
    if smax:
        return f"£{smax:,}"
    return ""


# ---------------------------------------------------------------------------
# 1. Adzuna API  (PRIMARY)
# ---------------------------------------------------------------------------

def adzuna_credentials() -> tuple[str, str]:
    """Return (app_id, app_key) from settings; empty strings when unset."""
    return (
        getattr(settings, "adzuna_app_id", "") or "",
        getattr(settings, "adzuna_app_key", "") or "",
    )


def fetch_adzuna(
    query: str,
    location: str = "UK",
    pages: int = 2,
    results_per_page: int = 25,
    session: Optional[requests.Session] = None,
) -> List[dict]:
    """Fetch UK jobs from the Adzuna API. Returns [] when unconfigured or on error.

    Docs: https://developer.adzuna.com/  (endpoint /v1/api/jobs/gb/search/{page}).
    The response schema this parses is Adzuna's real one: a top-level `results`
    list of objects with `title`, `description`, `company.display_name`,
    `location.display_name`, `salary_min`, `salary_max`, `redirect_url`,
    `created`.
    """
    app_id, app_key = adzuna_credentials()
    if not app_id or not app_key:
        logger.info("Adzuna: no credentials set (ADZUNA_APP_ID/ADZUNA_APP_KEY) - skipping")
        return []

    sess = session or requests.Session()
    jobs: List[dict] = []
    for page in range(1, pages + 1):
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": results_per_page,
            "what": query or "jobs",
            "where": location or "UK",
            "content-type": "application/json",
        }
        try:
            resp = sess.get(f"{ADZUNA_BASE}/{page}", params=params, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("Adzuna page %s network error: %s", page, exc)
            break
        if resp.status_code == 401:
            logger.warning("Adzuna 401 - app_id/app_key rejected; stopping")
            break
        if resp.status_code != 200:
            logger.warning("Adzuna page %s HTTP %s", page, resp.status_code)
            break
        results = (resp.json() or {}).get("results", [])
        if not results:
            break
        for item in results:
            job = make_job(
                title=item.get("title", ""),
                company=(item.get("company") or {}).get("display_name", ""),
                location=(item.get("location") or {}).get("display_name", location),
                salary=_format_salary(item.get("salary_min"), item.get("salary_max")),
                url=item.get("redirect_url", ""),
                description=item.get("description", ""),
                source="Adzuna",
                date_posted=(item.get("created") or "")[:10],
            )
            if job:
                jobs.append(job)
    logger.info("Adzuna: %s jobs for '%s'", len(jobs), query)
    return jobs


# ---------------------------------------------------------------------------
# 2. Reed API  (SECONDARY)
# ---------------------------------------------------------------------------

def reed_api_key() -> str:
    return getattr(settings, "reed_api_key", "") or ""


def fetch_reed(
    query: str,
    location: str = "United Kingdom",
    results: int = 50,
    session: Optional[requests.Session] = None,
) -> List[dict]:
    """Fetch UK jobs from the Reed API. Returns [] when unconfigured or on error.

    Docs: https://www.reed.co.uk/developers  (endpoint /api/1.0/search).
    Auth is HTTP Basic with the API key as the username and a blank password.
    Response schema parsed is Reed's real one: `results` list of objects with
    `jobTitle`, `employerName`, `locationName`, `minimumSalary`, `maximumSalary`,
    `jobDescription`, `jobUrl`, `date`.
    """
    key = reed_api_key()
    if not key:
        logger.info("Reed: no REED_API_KEY set - skipping")
        return []

    sess = session or requests.Session()
    params = {
        "keywords": query or "jobs",
        "locationName": location or "United Kingdom",
        "resultsToTake": results,
    }
    try:
        resp = sess.get(REED_BASE, params=params, auth=(key, ""), timeout=_HTTP_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning("Reed network error: %s", exc)
        return []
    if resp.status_code != 200:
        logger.warning("Reed HTTP %s", resp.status_code)
        return []

    jobs: List[dict] = []
    for item in (resp.json() or {}).get("results", []):
        job = make_job(
            title=item.get("jobTitle", ""),
            company=item.get("employerName", ""),
            location=item.get("locationName", location),
            salary=_format_salary(item.get("minimumSalary"), item.get("maximumSalary")),
            url=item.get("jobUrl", ""),
            description=item.get("jobDescription", ""),
            source="Reed",
            date_posted=item.get("date", ""),
        )
        if job:
            jobs.append(job)
    logger.info("Reed: %s jobs for '%s'", len(jobs), query)
    return jobs


# ---------------------------------------------------------------------------
# 3. Legacy HTML/scraper fallback  (UNRELIABLE - off by default)
# ---------------------------------------------------------------------------

def fetch_scraper_fallback(
    keywords: List[str],
    location: str = "United Kingdom",
    log_fn: Optional[Callable] = None,
) -> List[dict]:
    """Best-effort call into the legacy multi-board scraper.

    This is intentionally the LAST-choice live source: LinkedIn/Indeed and HTML
    boards frequently block or silently return nothing, so it must never be the
    primary path. Any failure returns [] rather than raising.
    """
    try:
        from backend.services.jobs.scraper import run_scraper_as_list
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning("Scraper fallback unavailable: %s", exc)
        return []
    try:
        raw = run_scraper_as_list(keywords, location, log_fn) or []
    except Exception as exc:
        logger.warning("Scraper fallback failed: %s", exc)
        return []
    # Normalise the scraper's shape into the canonical shape.
    jobs: List[dict] = []
    for r in raw:
        job = make_job(
            title=r.get("title", ""),
            company=r.get("company", ""),
            location=r.get("location", location),
            salary=r.get("salary", ""),
            url=r.get("url", ""),
            description=r.get("description", ""),
            source=r.get("source", "scraper"),
            date_posted=r.get("scraped_at", ""),
        )
        if job:
            jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# 4. Mock listings  (LAST RESORT - always available, clearly labelled)
# ---------------------------------------------------------------------------

# Realistic UK Skilled-Worker-relevant supply-chain roles at known licensed
# sponsors. Shaped exactly like a real fetched job so the rest of the pipeline
# (scoring, drafting, UI) behaves identically to a live run. The "source" is
# "Mock (no API key)" so the UI can flag that these are not live results.
MOCK_JOBS: List[dict] = [
    make_job(
        "Supply Chain Analyst", "DHL Supply Chain", "Coventry, West Midlands",
        "£32,000–£38,000",
        "https://careers.dhl.com/global/en",
        "Supply chain analyst supporting demand planning, inventory optimisation "
        "and transport KPIs. SAP and advanced Excel essential. Visa sponsorship "
        "available for the right candidate under the Skilled Worker route.",
        "Mock (no API key)",
    ),
    make_job(
        "Logistics Coordinator", "Kuehne+Nagel", "London",
        "£28,000–£34,000",
        "https://jobs.kuehne-nagel.com",
        "Coordinate ocean and air freight shipments, liaise with customs brokers, "
        "manage bookings and documentation (bill of lading, incoterms). Freight "
        "forwarding experience preferred. Skilled Worker sponsorship considered.",
        "Mock (no API key)",
    ),
    make_job(
        "Procurement Analyst", "NHS Supply Chain", "Nottingham",
        "£31,000–£37,000",
        "https://www.supplychain.nhs.uk/careers",
        "Analyse procurement spend, run supplier tenders, maintain contract data "
        "and support category managers. Strong Excel and stakeholder skills. NHS "
        "roles are eligible for Skilled Worker visa sponsorship.",
        "Mock (no API key)",
    ),
    make_job(
        "Demand Planner", "Unilever", "Leeds",
        "£35,000–£42,000",
        "https://careers.unilever.com",
        "Own the S&OP forecast for a category, drive demand planning accuracy and "
        "collaborate with commercial teams. SAP APO / IBP and forecasting "
        "experience valued. Sponsorship available for qualifying candidates.",
        "Mock (no API key)",
    ),
    make_job(
        "Import/Export Coordinator", "Maersk", "Liverpool",
        "£29,000–£35,000",
        "https://www.maersk.com/careers",
        "Manage end-to-end import/export operations, customs clearance and trade "
        "compliance (HS codes, incoterms). Container shipping background ideal. "
        "Certificate of Sponsorship available under the Skilled Worker route.",
        "Mock (no API key)",
    ),
    make_job(
        "Inventory Analyst", "Tesco", "Welwyn Garden City",
        "£30,000–£36,000",
        "https://www.tesco-careers.com",
        "Drive stock accuracy and availability across the network using data "
        "analysis, forecasting and replenishment tools. Advanced Excel and SQL "
        "welcome. Tesco is a licensed Skilled Worker visa sponsor.",
        "Mock (no API key)",
    ),
]


def mock_jobs() -> List[dict]:
    """Return a fresh copy of the demo listings (never mutate the module list)."""
    return [dict(j) for j in MOCK_JOBS]
