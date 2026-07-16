"""
backend/api/v1/endpoints/jobs_international.py

FastAPI router for the international job search pipeline.
Separate from the UK /jobs endpoint — can be called independently
or as part of an automation run.

Endpoints:
  POST /jobs/international/search   — quick scan (1 term, chosen countries)
  POST /jobs/international/full     — full deep scan (all terms, all countries)
  GET  /jobs/international/countries — list supported countries + metadata
"""
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from backend.services.jobs.international_scraper import (
    run_scraper_international_as_list,
    COUNTRY_CITIES,
    ADZUNA_COUNTRIES,
    INDEED_LOCALES,
)
from backend.services.monitor.run_store import add_event, get_run

router = APIRouter(prefix="/jobs/international", tags=["international-jobs"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class IntlSearchRequest(BaseModel):
    keywords:  List[str] = ["supply chain coordinator", "logistics coordinator"]
    countries: Optional[List[str]] = None  # None = all
    run_id:    Optional[str] = None


class IntlSearchResponse(BaseModel):
    total:           int
    by_country:      dict
    visa_sponsored:  int
    jobs:            list
    run_id:          Optional[str] = None


class CountryMeta(BaseModel):
    name:          str
    adzuna:        bool
    indeed_locale: str
    cities:        List[str]
    visa_notes:    str


# ---------------------------------------------------------------------------
# Country metadata — shown in Streamlit sidebar
# ---------------------------------------------------------------------------

COUNTRY_META = {
    "UAE": {
        "visa_notes": "Employer-sponsored residency visa. No income tax. "
                      "Major SC employers: DP World, Maersk, Agility, Aramex, Al-Futtaim. "
                      "1,300+ logistics visa sponsorship roles on ae.indeed.com (Jul 2026)."
    },
    "Singapore": {
        "visa_notes": "Employment Pass (EP) for degree holders earning SGD 5,000+/month. "
                      "Strong freight hub (PSA, Jurong Port). Fast approval via EPOL system."
    },
    "Australia": {
        "visa_notes": "Temporary Skill Shortage (TSS 482) visa. Logistics & procurement "
                      "on shortage occupation list. SEEK.com.au dominant. "
                      "Pathway to PR via 186/189 after 2 years."
    },
    "Canada": {
        "visa_notes": "Express Entry (NOC 1523 Logistics) + LMIA-exempt routes. "
                      "Job Bank Canada lists employer-sponsored roles. "
                      "Province-specific streams (BC, ON, AB) add further pathways."
    },
    "New Zealand": {
        "visa_notes": "Skilled Migrant Category (SMC). UK degree counts toward points. "
                      "Accredited employer work visa available. SEEK.co.nz dominant."
    },
    "India": {
        "visa_notes": "Multinationals (Maersk, DHL, Unilever, Infosys, TCS) actively "
                      "hire UK postgrads in Bangalore/Mumbai. No visa needed "
                      "if Bindu holds Indian citizenship/OCI."
    },
    "Remote": {
        "visa_notes": "~40% of SC analyst/coordinator roles now offer remote/hybrid. "
                      "No visa required. Platforms: Remote.com, Deel, Workana."
    },
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/countries", response_model=List[CountryMeta])
def list_countries():
    """Returns supported countries with visa notes and city lists."""
    result = []
    for country, cities in COUNTRY_CITIES.items():
        result.append(CountryMeta(
            name=country,
            adzuna=ADZUNA_COUNTRIES.get(country) is not None,
            indeed_locale=INDEED_LOCALES.get(country, "www"),
            cities=cities,
            visa_notes=COUNTRY_META.get(country, {}).get("visa_notes", ""),
        ))
    return result


@router.post("/search", response_model=IntlSearchResponse)
def search_international_jobs(payload: IntlSearchRequest):
    """Quick international scan — single keyword set, chosen countries."""
    if payload.run_id and not get_run(payload.run_id):
        raise HTTPException(status_code=404, detail="run_id not found")

    jobs = run_scraper_international_as_list(
        keywords=payload.keywords,
        countries=payload.countries,
    )

    by_country: dict = {}
    for j in jobs:
        c = j.get("country", "Unknown")
        by_country[c] = by_country.get(c, 0) + 1

    visa_count = sum(1 for j in jobs if j.get("visa_sponsored"))

    if payload.run_id:
        add_event(payload.run_id, {
            "step_name":   "international_job_search",
            "step_type":   "scrape",
            "status":      "completed",
            "message":     f"International search complete: {len(jobs)} jobs across {len(by_country)} countries",
            "output_summary": {"total": len(jobs), "by_country": by_country, "visa_sponsored": visa_count},
        })

    return IntlSearchResponse(
        total=len(jobs),
        by_country=by_country,
        visa_sponsored=visa_count,
        jobs=jobs[:200],  # cap payload size
        run_id=payload.run_id,
    )


@router.post("/full")
def full_international_scan(background_tasks: BackgroundTasks, run_id: Optional[str] = None):
    """
    Triggers full deep scan (all CORE_TERMS x all countries) as a background task.
    Returns immediately with a confirmation message.
    Use GET /monitor/{run_id} to track progress.
    """
    from backend.services.jobs.international_scraper import run_scraper_international_full
    background_tasks.add_task(run_scraper_international_full)
    return {"status": "started", "message": "Full international scan running in background. Check exports/ folder for results."}
