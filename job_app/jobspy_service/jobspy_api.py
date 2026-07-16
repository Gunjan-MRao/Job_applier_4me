from fastapi import FastAPI, Query
from typing import Optional
from jobspy import scrape_jobs
import math

app = FastAPI(title="JobSpy Service")


def safe_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/search_jobs")
def search_jobs(
    site_name: str = Query(..., description="linkedin, indeed, glassdoor, google"),
    search_term: str = Query(...),
    location: str = Query("United Kingdom"),
    results_wanted: int = Query(25),
    offset: int = Query(0),
    hours_old: Optional[int] = Query(None),
    easy_apply: Optional[bool] = Query(None),
):
    df = scrape_jobs(
        site_name=[site_name],
        search_term=search_term,
        location=location,
        results_wanted=results_wanted,
        offset=offset,
        hours_old=hours_old,
        country_indeed="UK",
        linkedin_fetch_description=True,
        easy_apply=easy_apply,
    )

    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "title": safe_value(row.get("title")),
                "company": safe_value(row.get("company")),
                "location": safe_value(row.get("location")),
                "job_url": safe_value(row.get("job_url")),
                "site": safe_value(row.get("site")),
                "date_posted": safe_value(row.get("date_posted")),
                "job_type": safe_value(row.get("job_type")),
                "salary_source": safe_value(row.get("salary_source")),
                "interval": safe_value(row.get("interval")),
                "min_amount": safe_value(row.get("min_amount")),
                "max_amount": safe_value(row.get("max_amount")),
                "currency": safe_value(row.get("currency")),
                "is_remote": safe_value(row.get("is_remote")),
                "emails": safe_value(row.get("emails")),
                "description": safe_value(row.get("description")),
                "company_industry": safe_value(row.get("company_industry")),
                "company_url": safe_value(row.get("company_url")),
                "company_logo": safe_value(row.get("company_logo")),
            }
        )

    return {
        "count": len(rows),
        "results": rows,
        "site_name": site_name,
        "offset": offset,
        "results_wanted": results_wanted,
    }