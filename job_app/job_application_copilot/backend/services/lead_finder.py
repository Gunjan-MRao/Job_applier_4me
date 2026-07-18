"""
lead_finder.py  — Recruiter / Talent Acquisition contact finder

Tries multiple strategies in order:
  1. Hunter.io Email Finder API   (needs HUNTER_API_KEY in .env)
  2. Apollo.io People Search API  (needs APOLLO_API_KEY in .env)
  3. LLM heuristic fallback       (guesses format from known patterns)

Returns the best email address found plus the strategy that found it.

Usage (async):
    from backend.services.lead_finder import find_recruiter_email
    result = await find_recruiter_email(company="Tesco", domain="tesco.com",
                                        job_title="Supply Chain Analyst")
    # result = {"email": "talent@tesco.com", "strategy": "hunter", "company": "Tesco"}

Usage (sync wrapper — for non-async callers such as automation_runtime.py):
    from backend.services.lead_finder import sync_find_recruiter_email
    result = sync_find_recruiter_email(company="Tesco")
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, Optional

import requests

from backend.core.config import settings

log = logging.getLogger(__name__)

# TA/HR title keywords we target in people searches
_TARGET_TITLES = [
    "talent acquisition", "recruiter", "hr manager",
    "people operations", "hiring manager", "engineering manager",
    "supply chain manager",
]


async def find_recruiter_email(
    company:   str,
    domain:    Optional[str] = None,
    job_title: str = "",
) -> Dict[str, Optional[str]]:
    """
    Attempt to find the best contact email for the given company.
    Returns a dict: {"email": str|None, "strategy": str, "company": str}
    Falls back gracefully through strategies so a missing API key never crashes.
    """
    domain = domain or _guess_domain(company)

    # Strategy 1 — Hunter.io
    if getattr(settings, "hunter_api_key", ""):
        email = await _hunter_find(domain, company)
        if email:
            log.info("Lead found via Hunter.io: %s", email)
            return {"email": email, "strategy": "hunter", "company": company}

    # Strategy 2 — Apollo.io
    if getattr(settings, "apollo_api_key", ""):
        email = await _apollo_find(company, job_title)
        if email:
            log.info("Lead found via Apollo.io: %s", email)
            return {"email": email, "strategy": "apollo", "company": company}

    # Strategy 3 — Heuristic pattern guess
    email = _heuristic_email(domain)
    log.debug("Lead heuristic guess: %s", email)
    return {"email": email, "strategy": "heuristic", "company": company}


def sync_find_recruiter_email(
    company:   str,
    domain:    Optional[str] = None,
    job_title: str = "",
) -> Dict[str, Optional[str]]:
    """
    Synchronous wrapper around find_recruiter_email.
    Safe to call from non-async code (e.g. automation_runtime.py threads).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We are already inside an event loop (e.g. FastAPI startup);
            # create a new loop in a thread to avoid deadlock.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(
                    asyncio.run,
                    find_recruiter_email(company, domain, job_title)
                )
                return fut.result(timeout=20)
        else:
            return loop.run_until_complete(
                find_recruiter_email(company, domain, job_title)
            )
    except Exception as exc:
        log.warning("sync_find_recruiter_email error: %s", exc)
        return {"email": _heuristic_email(domain or _guess_domain(company)),
                "strategy": "heuristic", "company": company}


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

async def _hunter_find(domain: str, company: str) -> Optional[str]:
    """Hunter.io Domain Search — returns highest-confidence TA/HR email."""
    try:
        r = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain":   domain,
                "company":  company,
                "api_key":  settings.hunter_api_key,
                "limit":    10,
            },
            timeout=10,
        )
        r.raise_for_status()
        data    = r.json().get("data", {})
        emails  = data.get("emails", [])
        for e in emails:
            pos = (e.get("position") or "").lower()
            if any(t in pos for t in _TARGET_TITLES):
                return e["value"]
        if emails:
            best = max(emails, key=lambda x: x.get("confidence", 0))
            return best["value"]
    except Exception as exc:
        log.debug("Hunter.io error: %s", exc)
    return None


async def _apollo_find(company: str, job_title: str) -> Optional[str]:
    """Apollo.io People Search — finds TA/HR person at the company."""
    try:
        target_titles = list(_TARGET_TITLES)
        if job_title:
            dept = job_title.split()[0].lower()
            target_titles.insert(0, f"{dept} manager")

        r = requests.post(
            "https://api.apollo.io/v1/mixed_people/search",
            headers={
                "Content-Type":  "application/json",
                "Cache-Control": "no-cache",
                "X-Api-Key":     settings.apollo_api_key,
            },
            json={
                "q_organization_name": company,
                "person_titles":       target_titles[:5],
                "page":                1,
                "per_page":            5,
            },
            timeout=15,
        )
        r.raise_for_status()
        people = r.json().get("people", [])
        for person in people:
            email = person.get("email")
            if email and "@" in email:
                return email
    except Exception as exc:
        log.debug("Apollo.io error: %s", exc)
    return None


def _heuristic_email(domain: Optional[str]) -> Optional[str]:
    """Guess a plausible recruiter email using common company patterns."""
    if not domain:
        return None
    return f"careers@{domain}"


def _guess_domain(company: str) -> str:
    """Naively guess company domain from name."""
    slug = re.sub(r"[^a-z0-9]", "", company.lower().split()[0])
    return f"{slug}.com"
