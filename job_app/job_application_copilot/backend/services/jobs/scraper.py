"""
backend/services/jobs/scraper.py

Full 4-phase job scraper (working code from standalone script, integrated
into the backend pipeline).  Call `run_scraper(log_fn)` to get a
pandas DataFrame, or `run_scraper_as_list(keywords, location, log_fn)`
for a plain list of dicts compatible with automation_runtime.

Phases:
  1. LinkedIn + Indeed via JobSpy
  2. APIs + RSS + general HTML boards
     (Adzuna API, Reed RSS, Indeed RSS, CV-Library, Totaljobs, Jobsite, CWJobs)
  3. Visa sponsorship boards + specialist freight boards
     (Tier2Jobs, SponsorshipJobs.io, UKVisaSponsorships, VisaJob UK,
      ShippingJobsLondon, Faststream)
  4. Government / NHS / Council / University
     (Find a Job GOV.UK, Civil Service Jobs, NHS Jobs, Trac, LG Jobs, jobs.ac.uk)

Scoring uses SC_KEYWORDS weighted vocabulary (supply chain, logistics,
freight forwarding, customs, sponsorship, etc.).
"""
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import requests
from bs4 import BeautifulSoup

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from jobspy import scrape_jobs as jobspy_scrape
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False

from backend.core.config import settings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = Path("exports")
DATA_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CORE_TERMS = [
    "supply chain analyst", "supply chain coordinator",
    "logistics coordinator", "procurement officer",
    "operations coordinator", "inventory analyst",
    "demand planner", "purchasing officer",
    "freight coordinator", "freight forwarder",
    "ocean freight coordinator", "import coordinator",
    "export coordinator", "import export coordinator",
    "customs coordinator", "shipping coordinator",
    "shipping operations coordinator", "sea freight coordinator",
    "air freight coordinator", "trade compliance coordinator",
    "freight operations",
]

SEARCH_LOCATIONS = [
    "London", "Manchester", "Birmingham", "Leeds", "Bristol",
    "Coventry", "Nottingham", "Liverpool", "Leicester", "Newcastle",
    "Glasgow", "Sheffield", "Remote", "United Kingdom",
]

JOBSPY_LOCATIONS = [
    "London", "Birmingham", "Manchester", "Coventry",
    "Leeds", "Bristol", "United Kingdom",
]

KNOWN_SPONSORS = [
    "tesco","sainsbury","asda","morrisons","lidl","aldi","waitrose",
    "boots","amazon","dhl","fedex","ups","dpd","royal mail",
    "kuehne nagel","maersk","ceva","geodis","gxo","db schenker",
    "dsv","bollore","sinotrans","toll group","mainfreight",
    "unilever","nestle","diageo","pepsico","coca-cola","heineken",
    "astrazeneca","gsk","pfizer","novartis","reckitt",
    "google","microsoft","oracle","sap","ibm","accenture","capgemini",
    "deloitte","kpmg","pwc","ey",
    "bp","shell","totalenergies","national grid",
    "nhs","nhs supply chain","nhs trust","foundation trust",
    "government","ministry of defence","cabinet office","home office",
    "department for transport","hmrc","network rail","transport for london",
    "university","college","ucl","imperial","oxford","cambridge",
    "barclays","hsbc","lloyds","natwest","jpmorgan","goldman sachs",
    "jaguar","land rover","bmw","toyota","honda","nissan",
    "bae systems","airbus","leonardo","babcock",
]

SC_KEYWORDS = [
    ("supply chain", 10), ("logistics", 8), ("procurement", 8),
    ("inventory", 7), ("operations", 5), ("demand planning", 8),
    ("warehouse", 5), ("purchasing", 7), ("sourcing", 6),
    ("sap", 5), ("erp", 4), ("forecasting", 6), ("stock", 4),
    ("vendor", 5), ("supplier", 5), ("kpi", 3), ("lean", 4),
    ("excel", 3), ("data analysis", 4), ("stakeholder", 3),
    ("graduate", 3), ("coordinator", 4), ("analyst", 3), ("planner", 4),
    ("s&op", 8), ("mrp", 6), ("wms", 6), ("tms", 5),
    ("freight", 8), ("freight forwarder", 10), ("freight forwarding", 10),
    ("container", 7), ("ocean freight", 9), ("sea freight", 9),
    ("air freight", 7), ("bill of lading", 9), ("customs clearance", 9),
    ("customs", 6), ("incoterms", 8), ("import", 5), ("export", 5),
    ("fcl", 7), ("lcl", 7), ("trade compliance", 8), ("hs code", 7),
    ("visa sponsorship", 15), ("skilled worker", 10),
    ("sponsorship available", 15), ("sponsorship", 8),
    ("tier 2", 8), ("tier2", 8),
]

NEGATIVE = [
    "10+ years", "15 years", "20 years", "head of",
    "director", "vp ", "vice president", "chief ", "c-suite",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str, log_fn: Optional[Callable] = None) -> None:
    try:
        text = str(msg).encode("ascii", errors="replace").decode()
    except Exception:
        text = "[unprintable]"
    if log_fn:
        log_fn(text)
    else:
        print(text, flush=True)


def is_likely_sponsor(company: str, description: str = "") -> bool:
    text = (company + " " + description).lower()
    return any(kw in text for kw in KNOWN_SPONSORS)


def safe_get(url: str, retries: int = 3, timeout: int = 15) -> requests.Response:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 + attempt)


def make_job(title, company, location, salary, description, job_url, source) -> Optional[dict]:
    if not title or not str(title).strip():
        return None

    def clean(val):
        if val is None:
            return ""
        s = str(val).strip()
        return "" if s.lower() in ("nan", "none", "n/a", "-") else s

    return {
        "title":       clean(title),
        "company":     clean(company),
        "location":    clean(location),
        "salary":      clean(salary),
        "description": clean(description),
        "url":         job_url or "",
        "source":      source,
        "scraped_at":  datetime.now().isoformat()[:10],
    }


# ---------------------------------------------------------------------------
# Phase 1 — LinkedIn + Indeed via JobSpy
# ---------------------------------------------------------------------------

def scrape_jobspy_uk(term: str, location: str, log_fn=None) -> List[dict]:
    jobs = []
    if not JOBSPY_AVAILABLE:
        return jobs
    try:
        df = jobspy_scrape(
            site_name=["indeed", "linkedin"],
            search_term=term,
            location=location,
            results_wanted=20,
            hours_old=72,
            country_indeed="UK",
        )
        if df is None or df.empty:
            return jobs
        for _, row in df.iterrows():
            j = make_job(
                str(row.get("title", "")), str(row.get("company", "")),
                str(row.get("location", location)),
                str(row.get("min_amount", "") or row.get("salary", "")),
                str(row.get("description", "")),
                str(row.get("job_url", "")),
                "LinkedIn/Indeed (JobSpy)",
            )
            if j:
                jobs.append(j)
        time.sleep(2)
    except Exception as e:
        _log(f"  JobSpy error ({location}): {e}", log_fn)
    return jobs


# ---------------------------------------------------------------------------
# Phase 2 — APIs + RSS + general HTML boards
# ---------------------------------------------------------------------------

def scrape_adzuna_api(term: str, location: str, log_fn=None) -> List[dict]:
    jobs = []
    app_id  = getattr(settings, "adzuna_app_id",  None) or ""
    app_key = getattr(settings, "adzuna_app_key", None) or ""
    if not app_id or not app_key:
        return jobs
    loc_map = {
        "London": "london", "Manchester": "manchester", "Birmingham": "birmingham",
        "Leeds": "leeds", "Bristol": "bristol", "Coventry": "coventry",
        "Nottingham": "nottingham", "Liverpool": "liverpool", "Leicester": "leicester",
        "Newcastle": "newcastle", "Glasgow": "glasgow", "Sheffield": "sheffield",
        "Remote": "uk", "United Kingdom": "uk",
    }
    loc_slug = loc_map.get(location, "uk")
    for page in range(1, 3):
        url = (
            f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
            f"?app_id={app_id}&app_key={app_key}"
            f"&results_per_page=20&what={requests.utils.quote(term)}"
            f"&where={loc_slug}&content-type=application/json"
        )
        try:
            resp = safe_get(url)
            data = resp.json()
            for item in data.get("results", []):
                sal = ""
                if item.get("salary_min"):
                    sal = f"£{int(item['salary_min'])}–£{int(item.get('salary_max', item['salary_min']))}"
                j = make_job(
                    item.get("title", ""),
                    item.get("company", {}).get("display_name", ""),
                    item.get("location", {}).get("display_name", location),
                    sal,
                    item.get("description", ""),
                    item.get("redirect_url", ""),
                    "Adzuna",
                )
                if j:
                    jobs.append(j)
            time.sleep(0.5)
        except Exception as e:
            _log(f"  Adzuna API error ({location}): {e}", log_fn)
            break
    return jobs


def scrape_reed_rss(term: str, location: str, log_fn=None) -> List[dict]:
    jobs = []
    url = (
        f"https://www.reed.co.uk/jobs/rss?keywords={requests.utils.quote(term)}"
        f"&location={requests.utils.quote(location)}&proximity=20"
    )
    try:
        resp = safe_get(url)
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item")[:20]:
            title    = (item.findtext("title") or "").strip()
            link     = (item.findtext("link") or "").strip()
            desc_raw = item.findtext("description") or ""
            desc     = BeautifulSoup(desc_raw, "html.parser").get_text(separator=" ", strip=True)
            company, salary = "", ""
            for part in desc.split("|"):
                p = part.strip()
                if "£" in p or "per" in p.lower():
                    salary = p
                elif not company and p and len(p) < 80:
                    company = p
            j = make_job(title, company, location, salary, desc, link, "Reed")
            if j:
                jobs.append(j)
        time.sleep(1)
    except Exception as e:
        _log(f"  Reed RSS error ({location}): {e}", log_fn)
    return jobs


def scrape_indeed_rss(term: str, location: str, log_fn=None) -> List[dict]:
    jobs = []
    url = (
        f"https://uk.indeed.com/rss?q={requests.utils.quote(term)}"
        f"&l={requests.utils.quote(location)}&sort=date&limit=20"
    )
    try:
        resp = safe_get(url)
        soup = BeautifulSoup(resp.content, "lxml-xml")
        for item in soup.find_all("item")[:20]:
            try:
                title   = item.find("title").get_text(strip=True) if item.find("title") else ""
                link    = item.find("link").get_text(strip=True) if item.find("link") else ""
                desc_r  = item.find("description").get_text(strip=True) if item.find("description") else ""
                desc    = BeautifulSoup(desc_r, "html.parser").get_text(strip=True)
                src_tag = item.find("source")
                company = src_tag.get_text(strip=True) if src_tag else ""
                j = make_job(title, company, location, "", desc, link, "Indeed")
                if j:
                    jobs.append(j)
            except Exception:
                continue
        time.sleep(1)
    except Exception as e:
        _log(f"  Indeed RSS error ({location}): {e}", log_fn)
    return jobs


def _html_board(run_name, url, card_sel, title_sel, co_sel, loc_sel,
                sal_sel, desc_sel, base_url, limit=20, log_fn=None) -> List[dict]:
    jobs = []
    try:
        resp = safe_get(url)
        if resp.status_code != 200:
            return jobs
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
        for card in soup.select(card_sel)[:limit]:
            try:
                te = card.select_one(title_sel)
                if not te:
                    continue
                href = te.get("href", "")
                job_url = href if href.startswith("http") else f"{base_url}{href}"
                ce = card.select_one(co_sel) if co_sel else None
                le = card.select_one(loc_sel) if loc_sel else None
                se = card.select_one(sal_sel) if sal_sel else None
                de = card.select_one(desc_sel) if desc_sel else None
                j = make_job(
                    te.get_text(strip=True),
                    ce.get_text(strip=True) if ce else "",
                    le.get_text(strip=True) if le else "UK",
                    se.get_text(strip=True) if se else "",
                    de.get_text(strip=True) if de else "",
                    job_url, run_name,
                )
                if j:
                    jobs.append(j)
            except Exception:
                continue
        time.sleep(1)
    except Exception as e:
        _log(f"  {run_name} error: {e}", log_fn)
    return jobs


def scrape_cv_library(term: str, location: str, log_fn=None) -> List[dict]:
    url = (
        f"https://www.cv-library.co.uk/search-jobs?keywords={requests.utils.quote(term)}"
        f"&geo={requests.utils.quote(location)}&us=1&distance=20"
    )
    return _html_board(
        "CV-Library", url,
        "li.job, article.job, .job-result",
        "h2 a, h3 a, .job-title a, a.job-title",
        ".company, .job-company, .employer",
        ".location, .job-location",
        ".salary, .job-salary",
        ".description, .job-description, .summary",
        "https://www.cv-library.co.uk", log_fn=log_fn,
    )


def scrape_totaljobs(term: str, location: str, log_fn=None) -> List[dict]:
    url = (
        f"https://www.totaljobs.com/jobs?keywords={requests.utils.quote(term)}"
        f"&location={requests.utils.quote(location)}&radius=50"
    )
    return _html_board(
        "Totaljobs", url,
        "article.job-result, div.job-result-item, [data-at='job-item'], .job-card",
        "h2 a, h3 a, .job-title a, [data-at='job-item-title'] a",
        ".recruiter, .company-name, [data-at='job-item-company-name']",
        ".location, .job-location, [data-at='job-item-location']",
        ".salary, [data-at='job-item-salary']",
        ".job-description, .summary, [data-at='job-item-teaser']",
        "https://www.totaljobs.com", log_fn=log_fn,
    )


def scrape_jobsite(term: str, location: str, log_fn=None) -> List[dict]:
    url = (
        f"https://www.jobsite.co.uk/jobs/{term.replace(' ', '-')}"
        f"/in-{location.replace(' ', '-')}"
    )
    return _html_board(
        "Jobsite", url,
        "article.job-result, div.job-result-item, .job-card",
        "h2 a, h3 a, .job-title a",
        ".recruiter, .company-name",
        ".location, .job-location",
        ".salary",
        ".job-description, .summary",
        "https://www.jobsite.co.uk", log_fn=log_fn,
    )


def scrape_cwjobs(term: str, location: str, log_fn=None) -> List[dict]:
    url = (
        f"https://www.cwjobs.co.uk/jobs?keywords={requests.utils.quote(term)}"
        f"&location={requests.utils.quote(location)}&radius=50"
    )
    return _html_board(
        "CWJobs", url,
        "article.job-result, .job-result-item, .job-card",
        "h2 a, h3 a, .job-title a",
        ".recruiter, .company-name",
        ".location",
        ".salary",
        ".summary, .job-description",
        "https://www.cwjobs.co.uk", log_fn=log_fn,
    )


# ---------------------------------------------------------------------------
# Phase 3 — Visa sponsorship + specialist freight boards
# ---------------------------------------------------------------------------

def scrape_tier2jobs(term: str, log_fn=None) -> List[dict]:
    url = f"https://www.tier2jobs.co.uk/jobs?q={requests.utils.quote(term)}"
    return _html_board(
        "Tier2Jobs (Visa)", url,
        "div.job, li.job, article, .job-listing, .job-card",
        "h2 a, h3 a, .title a, .job-title a, a",
        ".company, .employer", ".location", ".salary", ".description, .summary",
        "https://www.tier2jobs.co.uk", log_fn=log_fn,
    )


def scrape_sponsorship_jobs_io(term: str, log_fn=None) -> List[dict]:
    url = f"https://sponsorshipjobs.io/jobs?q={requests.utils.quote(term)}&country=uk"
    return _html_board(
        "SponsorshipJobs (Visa)", url,
        "div.job, article.job, li.job-item, .job-card, .vacancy",
        "h2 a, h3 a, .title a, .job-title, a",
        ".company, .employer", ".location", ".salary", ".description, .summary",
        "https://sponsorshipjobs.io", log_fn=log_fn,
    )


def scrape_uk_visa_sponsorships(term: str, log_fn=None) -> List[dict]:
    url = f"https://ukvisasponsorships.co.uk/jobs?q={requests.utils.quote(term)}"
    return _html_board(
        "UKVisaSponsorships (Visa)", url,
        "div.job, article, li.vacancy, .job-card, .job-listing",
        "h2 a, h3 a, .title a, .job-title a, a",
        ".company, .employer, .trust", ".location", ".salary", ".description, .summary",
        "https://ukvisasponsorships.co.uk", log_fn=log_fn,
    )


def scrape_visajob_uk(term: str, log_fn=None) -> List[dict]:
    url = f"https://visajob.co.uk/jobs?q={requests.utils.quote(term)}&country=UK"
    return _html_board(
        "VisaJob UK (Visa)", url,
        "div.job-card, article.job, li.job, .vacancy, .job",
        "h2 a, h3 a, .job-title a, a.title, a",
        ".company, .employer, .organisation", ".location", ".salary", ".description, .summary",
        "https://visajob.co.uk", log_fn=log_fn,
    )


def scrape_shippingjobs_london(term: str, log_fn=None) -> List[dict]:
    url = f"https://shippingjobslondon.co.uk/jobs?q={requests.utils.quote(term)}"
    return _html_board(
        "ShippingJobsLondon (Freight)", url,
        "div.job, li.job, article, .job-listing, .job-card, .vacancy",
        "h2 a, h3 a, .job-title a, .title a, a",
        ".company, .employer, .recruiter", ".location, .job-location",
        ".salary, .job-salary", ".description, .summary, .job-description",
        "https://shippingjobslondon.co.uk", log_fn=log_fn,
    )


def scrape_faststream(term: str, log_fn=None) -> List[dict]:
    url = f"https://www.faststream.com/jobs/?search={requests.utils.quote(term)}&location=United+Kingdom"
    return _html_board(
        "Faststream (Freight)", url,
        "div.job, li.job, article, .job-listing, .job-card, .vacancy, .position",
        "h2 a, h3 a, .job-title a, .title a, a",
        ".company, .employer, .client", ".location, .job-location",
        ".salary, .job-salary", ".description, .summary, .job-description",
        "https://www.faststream.com", log_fn=log_fn,
    )


# ---------------------------------------------------------------------------
# Phase 4 — Government / NHS / Council / University
# ---------------------------------------------------------------------------

def scrape_jobs_gov_uk(term: str, log_fn=None) -> List[dict]:
    url = (
        f"https://findajob.dwp.gov.uk/search?q={requests.utils.quote(term)}"
        f"&where=United+Kingdom&d=30&pp=25"
    )
    return _html_board(
        "Find a Job (Gov)", url,
        "div.search-result, li.search-result, article.search-result, .govuk-summary-list",
        "h3 a, h2 a, .job-title a, a",
        ".employer, .company, dt ~ dd", ".location, .address",
        ".salary, .pay", ".description, .snippet, p",
        "https://findajob.dwp.gov.uk", log_fn=log_fn,
    )


def scrape_civil_service(term: str, log_fn=None) -> List[dict]:
    url = (
        f"https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi"
        f"?jcode=&pageaction=searchbykey&keyword={requests.utils.quote(term)}"
        f"&button_submit.x=0&button_submit.y=0"
    )
    return _html_board(
        "Civil Service Jobs", url,
        "li.search-results-job-box, div.job-result, .search-results-job",
        "h3 a, h2 a, .job-title, a[href*='vacancy']",
        ".organisation, .employer, .department", ".location, .job-location",
        ".salary, .job-salary", "",
        "https://www.civilservicejobs.service.gov.uk", log_fn=log_fn,
    )


def scrape_nhs_jobs(term: str, log_fn=None) -> List[dict]:
    url = (
        f"https://www.jobs.nhs.uk/candidate/search/results"
        f"?keyword={requests.utils.quote(term)}&location=United+Kingdom&distance=200"
    )
    return _html_board(
        "NHS Jobs", url,
        "li.vacancy, div.vacancy-item, article, .nhsuk-card, [data-test='vacancy-item']",
        "h2 a, h3 a, .vacancy-title a, a.vacancy-link, [data-test='vacancy-title'] a",
        ".employer, .organisation, .trust-name, [data-test='employer-name']",
        ".location, .vacancy-location, [data-test='vacancy-location']",
        ".salary, .pay-scheme, [data-test='vacancy-salary']",
        ".description, .vacancy-description, .summary",
        "https://www.jobs.nhs.uk", log_fn=log_fn,
    )


def scrape_trac_jobs(term: str, log_fn=None) -> List[dict]:
    url = f"https://www.trac.jobs/jobs/search?keywords={requests.utils.quote(term)}&location=United+Kingdom"
    return _html_board(
        "Trac (NHS)", url,
        "div.job-result, li.job, article, .job-listing",
        "h2 a, h3 a, .job-title a, a",
        ".employer, .trust, .organisation", ".location",
        ".salary", ".description, .summary",
        "https://www.trac.jobs", log_fn=log_fn,
    )


def scrape_local_gov_jobs(term: str, log_fn=None) -> List[dict]:
    url = f"https://www.lgjobs.com/vacancies?keywords={requests.utils.quote(term)}&location=United+Kingdom&distance=200"
    return _html_board(
        "LG Jobs (Local Gov)", url,
        "li.vacancy, div.vacancy, article.vacancy, .vacancy-item",
        "h2 a, h3 a, .vacancy-title a, a[href*='vacancy']",
        ".organisation, .employer, .council", ".location",
        ".salary", ".description, .summary",
        "https://www.lgjobs.com", log_fn=log_fn,
    )


def scrape_jobs_ac_uk(term: str, log_fn=None) -> List[dict]:
    url = f"https://www.jobs.ac.uk/search/?keywords={requests.utils.quote(term)}&location=United+Kingdom&distance=200"
    return _html_board(
        "jobs.ac.uk (Uni)", url,
        "div.r-item, li.job, article.job, .job-result",
        "h2 a, h3 a, .title a, a.job-title",
        ".employer, .institution, .university", ".location",
        ".salary", ".description, .summary",
        "https://www.jobs.ac.uk", log_fn=log_fn,
    )


# ---------------------------------------------------------------------------
# Description enricher
# ---------------------------------------------------------------------------

def fetch_description(job_url: str, source: str) -> str:
    if not job_url:
        return ""
    try:
        resp = safe_get(job_url, timeout=12)
        soup = BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
        selectors = {
            "reed":          "[data-qa='jobDescription'], .description, #jobDescription",
            "indeed":        "#jobDescriptionText, .jobsearch-jobDescriptionText",
            "civil service": ".job-description, #vac_display_job_description",
            "nhs":           ".nhsuk-body-s, .job-description, #job-description",
            "trac":          ".job-description, .vacancy-description",
            "gov":           ".job-description, .content, main",
            "adzuna":        ".adp-body, .jobad-desc",
            "freight":       ".job-description, .description, main article, main",
        }
        el = None
        for key, sel in selectors.items():
            if key in source.lower():
                el = soup.select_one(sel)
                break
        if not el:
            el = soup.select_one(".job-description, [itemprop='description'], main article, #job-description, main")
        return el.get_text(strip=True)[:3000] if el else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Weighted SC scorer
# ---------------------------------------------------------------------------

def score_job(job: dict, visa_bonus: bool = False) -> int:
    text = (str(job.get("title", "")) + " " + str(job.get("description", ""))).lower()
    score = sum(pts for kw, pts in SC_KEYWORDS if kw in text)
    if any(neg in text for neg in NEGATIVE):
        score = max(0, score - 10)
    if visa_bonus or job.get("visa_sponsored"):
        score += 8
    src = str(job.get("source", ""))
    if any(x in src for x in ["Visa", "Tier2", "Sponsored", "UKHired"]):
        score += 12
    if any(x in src for x in ["NHS", "Gov", "Civil", "Council", "LG Jobs", "Trac", "Uni"]):
        score += 5
    if any(x in src for x in ["Freight", "Shipping", "Faststream"]):
        score += 6
    if "JobSpy" in src:
        score += 4
    return score


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def run_scraper(log_fn=None):
    """Run all 4 phases. Returns a sorted pandas DataFrame (or list if pandas unavailable)."""
    all_jobs = []

    _log("[PHASE 1] LinkedIn + Indeed via JobSpy...", log_fn)
    for term in CORE_TERMS:
        for location in JOBSPY_LOCATIONS:
            _log(f"  JobSpy: '{term}' in {location}", log_fn)
            all_jobs += scrape_jobspy_uk(term, location, log_fn)
            time.sleep(1)

    _log(f"[PHASE 2] General boards across {len(SEARCH_LOCATIONS)} UK locations...", log_fn)
    for term in CORE_TERMS:
        for loc in SEARCH_LOCATIONS:
            all_jobs += scrape_adzuna_api(term, loc, log_fn)
            all_jobs += scrape_reed_rss(term, loc, log_fn)
            all_jobs += scrape_indeed_rss(term, loc, log_fn)
            all_jobs += scrape_cv_library(term, loc, log_fn)
            all_jobs += scrape_totaljobs(term, loc, log_fn)
            all_jobs += scrape_jobsite(term, loc, log_fn)
            all_jobs += scrape_cwjobs(term, loc, log_fn)
            time.sleep(0.5)

    _log("[PHASE 3] Visa sponsorship + specialist freight boards...", log_fn)
    for term in CORE_TERMS:
        all_jobs += scrape_tier2jobs(term, log_fn)
        all_jobs += scrape_sponsorship_jobs_io(term, log_fn)
        all_jobs += scrape_uk_visa_sponsorships(term, log_fn)
        all_jobs += scrape_visajob_uk(term, log_fn)
        all_jobs += scrape_shippingjobs_london(term, log_fn)
        all_jobs += scrape_faststream(term, log_fn)
        time.sleep(1)

    _log("[PHASE 4] Public sector & government boards...", log_fn)
    for term in CORE_TERMS:
        all_jobs += scrape_jobs_gov_uk(term, log_fn)
        all_jobs += scrape_civil_service(term, log_fn)
        all_jobs += scrape_nhs_jobs(term, log_fn)
        all_jobs += scrape_trac_jobs(term, log_fn)
        all_jobs += scrape_local_gov_jobs(term, log_fn)
        all_jobs += scrape_jobs_ac_uk(term, log_fn)
        time.sleep(1)

    if not all_jobs:
        _log("[WARNING] No jobs scraped.", log_fn)
        return [] if not PANDAS_AVAILABLE else __import__("pandas").DataFrame()

    # --- Dedup ---
    seen, unique = set(), []
    for j in all_jobs:
        key = (j["title"].lower().strip(), j.get("company", "").lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(j)
    _log(f"[DEDUP] {len(all_jobs)} raw → {len(unique)} unique", log_fn)

    # --- Sponsor flag + score ---
    for j in unique:
        j["visa_sponsored"] = is_likely_sponsor(j.get("company", ""), j.get("description", ""))
        src = j.get("source", "")
        if any(x in src for x in ["Visa", "Tier2", "Sponsored", "NHS", "Gov", "Civil", "LG Jobs", "Trac", "Uni"]):
            j["visa_sponsored"] = True
        j["match_score"] = score_job(j)

    unique.sort(key=lambda x: x["match_score"], reverse=True)

    # --- Enrich top 50 ---
    enriched = 0
    for j in unique[:100]:
        if "JobSpy" in j.get("source", ""):
            continue
        if len(j.get("description", "")) < 100:
            full = fetch_description(j.get("url", ""), j.get("source", ""))
            if full:
                j["description"] = full
                j["match_score"] = score_job(j)
            enriched += 1
            if enriched >= 50:
                break
        time.sleep(0.4)

    unique.sort(key=lambda x: x["match_score"], reverse=True)

    # --- Save CSV ---
    if PANDAS_AVAILABLE:
        import pandas as pd
        df = pd.DataFrame(unique)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        out = DATA_DIR / f"jobs_{ts}.csv"
        df.to_csv(out, index=False, encoding="utf-8")
        _log(f"[SAVED] {len(df)} jobs -> exports/{out.name}", log_fn)
        return df

    return unique


def run_scraper_as_list(keywords: list, location: str, log_fn=None) -> List[dict]:
    """Lighter wrapper used by automation_runtime — single keyword set, single location."""
    all_jobs: List[dict] = []
    term = " ".join(keywords[:3]) or "supply chain logistics"
    all_jobs += scrape_jobspy_uk(term, location, log_fn)
    all_jobs += scrape_reed_rss(term, location, log_fn)
    all_jobs += scrape_adzuna_api(term, location, log_fn)
    all_jobs += scrape_cv_library(term, location, log_fn)
    all_jobs += scrape_totaljobs(term, location, log_fn)
    all_jobs += scrape_cwjobs(term, location, log_fn)
    all_jobs += scrape_tier2jobs(term, log_fn)
    all_jobs += scrape_uk_visa_sponsorships(term, log_fn)
    all_jobs += scrape_nhs_jobs(term, log_fn)
    all_jobs += scrape_jobs_gov_uk(term, log_fn)
    seen, unique = set(), []
    for j in all_jobs:
        key = (j["title"].lower().strip(), j.get("company", "").lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(j)
    for j in unique:
        j["visa_sponsored"] = is_likely_sponsor(j.get("company", ""), j.get("description", ""))
        j["match_score"]    = score_job(j)
    unique.sort(key=lambda x: x["match_score"], reverse=True)
    return unique
