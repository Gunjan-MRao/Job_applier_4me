"""
lead_finder.py  — Recruiter / Talent Acquisition contact finder

Tries multiple strategies in order:
  1. Hunter.io Email Finder API   (needs HUNTER_API_KEY in .env)
  2. Apollo.io People Search API  (needs APOLLO_API_KEY in .env)
  3. LLM heuristic fallback       (guesses format from known patterns)

Returns the best email address found, or None.

Usage:
    from backend.services.lead_finder import find_recruiter_email
    email = await find_recruiter_email(company="Tesco", domain="tesco.com",
                                       job_title="Supply Chain Analyst")
"""
from __future__ import annotations

import logging
import re
from typing import Optional

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
) -> Optional[str]:
    """Attempt to find the best contact email for the given company.

    Falls back gracefully through strategies so a missing API key doesn't crash.
    """
    domain = domain or _guess_domain(company)

    # Strategy 1 — Hunter.io
    if settings.hunter_api_key:
        email = await _hunter_find(domain, company)
        if email:
            log.info("Lead found via Hunter.io: %s", email)
            return email

    # Strategy 2 — Apollo.io
    if settings.apollo_api_key:
        email = await _apollo_find(company, job_title)
        if email:
            log.info("Lead found via Apollo.io: %s", email)
            return email

    # Strategy 3 — Heuristic pattern guess
    email = _heuristic_email(domain)
    log.debug("Lead heuristic guess: %s", email)
    return email


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
        # Prefer HR/TA role matches
        for e in emails:
            pos = (e.get("position") or "").lower()
            if any(t in pos for t in _TARGET_TITLES):
                return e["value"]
        # Fallback: highest confidence score
        if emails:
            best = max(emails, key=lambda x: x.get("confidence", 0))
            return best["value"]
    except Exception as exc:
        log.debug("Hunter.io error: %s", exc)
    return None


async def _apollo_find(company: str, job_title: str) -> Optional[str]:
    """Apollo.io People Search — finds TA/HR person at the company."""
    try:
        # Build seniority-aware title list
        target_titles = [t for t in _TARGET_TITLES]
        if job_title:
            dept = job_title.split()[0].lower()  # e.g. "supply" from "Supply Chain Analyst"
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
    guesses = [
        f"careers@{domain}",
        f"recruitment@{domain}",
        f"talent@{domain}",
        f"hr@{domain}",
    ]
    return guesses[0]   # caller should ideally validate before sending


def _guess_domain(company: str) -> str:
    """Naively guess company domain from name."""
    slug = re.sub(r"[^a-z0-9]", "", company.lower().split()[0])
    return f"{slug}.com"
