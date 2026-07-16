"""
backend/services/jobs/international_scraper.py

International job scraper — separate pipeline entity that runs alongside the
UK scraper.  Targets countries with strong supply chain / logistics markets
that actively hire UK-educated candidates and sponsor visas:

  • UAE / Dubai       — No income tax; massive logistics hub (DP World / JAFZA)
  • Singapore         — Global freight hub; EPaSS / Employment Pass for degree holders
  • Australia         — Skilled visa (482/189); strong freight & 3PL sector
  • Canada            — Express Entry friendly; large 3PL & e-commerce sector
  • New Zealand       — Skilled Migrant Category; quality of life; SEEK dominant
  • India             — Large multinational hubs (Infosys, TCS, Reliance, Maersk)
  • Remote            — Remote-first supply chain / ops roles, any timezone

Key design decisions:
  - Uses ONLY Adzuna API (reliable, no blocking) + Indeed RSS (no scraping)
    for Phase 1.  HTML scraping of specialist boards in Phase 2 as a bonus.
  - run_scraper_international_as_list() is the entry point for automation_runtime.
  - All results carry a `country` field so the frontend can filter by region.
  - Saves to exports/jobs_international_<timestamp>.csv
  - 0 jobs is never a crash — always returns an empty list gracefully.

Research basis:
  - UAE:  1,300+ supply chain visa sponsorship roles on ae.indeed.com (Jul 2026)
    Major sponsors: DP World, Maersk, Agility, Aramex, Al-Futtaim, Emirates Group
  - SG:   Employment Pass available for degree + SGD 5k+ salary; JobStreet dominant
  - AU:   TSS 482 visa; SEEK.com.au the #1 board; shortage occupation list includes
    logistics & procurement
  - CA:   Express Entry NOC 1523 (logistics); Job Bank Canada is authoritative
  - NZ:   Skilled Migrant Category; SEEK.co.nz dominant
  - IN:   Multinational MNCs in Bangalore/Mumbai actively hire UK postgrads
  - Remote: ~40% of supply chain analyst/coordinator ads now offer hybrid/remote
"""
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import requests
from bs4 import BeautifulSoup

from backend.core.config import settings

# ---------------------------------------------------------------------------
# Constants
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

# Adzuna country slugs (None = not supported by Adzuna)
ADZUNA_COUNTRIES = {
    "Singapore":   "sg",
    "Australia":   "au",
    "Canada":      "ca",
    "New Zealand": "nz",
    "UAE":         None,  # Not on Adzuna; use Indeed RSS instead
    "India":       None,  # Not on Adzuna; use Indeed RSS instead
    "Remote":      "gb",  # Use UK Adzuna with 'remote' keyword
}

# Indeed locale codes
INDEED_LOCALES = {
    "UAE":         "ae",
    "Singapore":   "sg",
    "Australia":   "au",
    "Canada":      "ca",
    "New Zealand": "nz",
    "India":       "in",
    "Remote":      "www",
}

# Representative cities for Indeed RSS (kept small to avoid rate limiting)
COUNTRY_CITIES = {
    "UAE":         ["Dubai", "Abu Dhabi"],
    "Singapore":   ["Singapore"],
    "Australia":   ["Sydney", "Melbourne", "Brisbane"],
    "Canada":      ["Toronto", "Vancouver", "Calgary"],
    "New Zealand": ["Auckland", "Wellington"],
    "India":       ["Bangalore", "Mumbai", "Hyderabad"],
    "Remote":      ["Remote"],
}

# Lean keyword set for international searches
CORE_TERMS = [
    "supply chain coordinator",
    "logistics coordinator",
    "freight coordinator",
    "procurement officer",
    "freight forwarder",
    "import export coordinator",
    "customs coordinator",
    "demand planner",
    "operations coordinator",
    "supply chain analyst",
]

# Companies known to sponsor international visas in SC/logistics
INTL_SPONSORS = [
    "dhl", "fedex", "ups", "maersk", "cma cgm", "hapag-lloyd",
    "kuehne nagel", "dsv", "ceva", "geodis", "gxo", "db schenker",
    "agility", "expeditors", "ch robinson", "toll group", "mainfreight",
    "dp world", "aramex", "al-futtaim", "emirates", "etihad", "dnata",
    "amazon", "ikea", "unilever", "nestle", "pepsico", "diageo",
    "samsung", "lg", "siemens", "bosch", "honeywell",
    "toyota", "honda", "nissan", "bmw", "volkswagen",
    "accenture", "deloitte", "kpmg", "pwc",
    "ibm", "oracle", "sap", "microsoft",
    "wipro", "infosys", "tata", "hcl", "cognizant",
    "singpost", "psa corporation", "jurong port",
    "toll holdings", "linfox", "australia post", "bhp",
    "fonterra", "port of auckland",
    "canadian tire", "loblaws", "bombardier", "brookfield",
    "reliance", "mahindra", "adani", "allcargo", "transworld",
]

SC_KEYWORDS = [
    ("supply chain", 10), ("logistics", 8), ("procurement", 8),
    ("inventory", 7), ("operations", 5), ("demand planning", 8),
    ("warehouse", 5), ("purchasing", 7), ("sourcing", 6),
    ("sap", 5), ("erp", 4), ("forecasting", 6),
    ("vendor", 5), ("supplier", 5), ("lean", 4),
    ("freight", 8), ("freight forwarder", 10), ("freight forwarding", 10),
    ("container", 7), ("ocean freight", 9), ("sea freight", 9),
    ("air freight", 7), ("bill of lading", 9), ("customs clearance", 9),
    ("customs", 6), ("incoterms", 8), ("import", 5), ("export", 5),
    ("fcl", 7), ("lcl", 7), ("trade compliance", 8),
    # Relocation / visa signals — given high weight as these are Bindu’s key filter
    ("visa sponsorship", 15), ("work permit", 12), ("relocation", 10),
    ("sponsorship", 8), ("sponsored", 8), ("skilled worker", 10),
    ("sponsorship available", 15), ("visa support", 12),
    ("relocation package", 10), ("expat", 6),
    # UK degree advantage signals
    ("uk educated", 8), ("uk degree", 8), ("masters", 5),
    ("msc", 5), ("postgraduate", 5),
    # Remote
    ("remote", 4), ("hybrid", 3), ("work from anywhere", 6),
]

NEGATIVE = [
    "10+ years", "15 years", "20 years", "head of",
    "director", "vp ", "vice president", "chief ", "c-suite",
    "citizen only", "no sponsorship", "must be citizen",
    "permanent resident only", "no work permit",
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


def make_job(title, company, location, salary, description, job_url, source, country) -> Optional[dict]:
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
        "country":     country,
        "scraped_at":  datetime.now().isoformat()[:10],
    }


def is_intl_sponsor(company: str, description: str = "") -> bool:
    text = (company + " " + description).lower()
    return any(kw in text for kw in INTL_SPONSORS)


def score_job(job: dict) -> int:
    text = (str(job.get("title", "")) + " " + str(job.get("description", ""))).lower()
    score = sum(pts for kw, pts in SC_KEYWORDS if kw in text)
    if any(neg in text for neg in NEGATIVE):
        score = max(0, score - 15)
    if job.get("visa_sponsored"):
        score += 10
    if is_intl_sponsor(job.get("company", ""), job.get("description", "")):
        score += 8
    # Bonus for specialist boards
    src = str(job.get("source", ""))
    if any(x in src for x in ["GulfTalent", "Bayt", "Naukri", "NaukriGulf", "SEEK",
                               "JobStreet", "JobBank", "Shine"]):
        score += 5
    return score


# ---------------------------------------------------------------------------
# Phase 1 — Adzuna API (most reliable, no blocking, free tier = 250 calls/day)
# ---------------------------------------------------------------------------

def scrape_adzuna_intl(term: str, country: str, log_fn=None) -> List[dict]:
    jobs = []
    slug = ADZUNA_COUNTRIES.get(country)
    if not slug:
        return jobs
    app_id  = getattr(settings, "adzuna_app_id",  None) or ""
    app_key = getattr(settings, "adzuna_app_key", None) or ""
    if not app_id or not app_key:
        _log(f"  [Adzuna] No API keys set — skipping {country}. Add ADZUNA_APP_ID + ADZUNA_APP_KEY to .env", log_fn)
        return jobs
    search_term = f"{term} remote" if country == "Remote" else term
    for page in range(1, 3):
        url = (
            f"https://api.adzuna.com/v1/api/jobs/{slug}/search/{page}"
            f"?app_id={app_id}&app_key={app_key}"
            f"&results_per_page=20&what={requests.utils.quote(search_term)}"
            f"&content-type=application/json"
        )
        if country == "Remote":
            url += "&full_time=1&permanent=1"
        try:
            resp = safe_get(url)
            data = resp.json()
            for item in data.get("results", []):
                sal = ""
                if item.get("salary_min"):
                    sal = f"{int(item['salary_min'])}–{int(item.get('salary_max', item['salary_min']))}"
                j = make_job(
                    item.get("title", ""),
                    item.get("company", {}).get("display_name", ""),
                    item.get("location", {}).get("display_name", country),
                    sal,
                    item.get("description", ""),
                    item.get("redirect_url", ""),
                    "Adzuna",
                    country,
                )
                if j:
                    jobs.append(j)
            time.sleep(0.5)
        except Exception as e:
            _log(f"  Adzuna ({country}) error: {e}", log_fn)
            break
    return jobs


# ---------------------------------------------------------------------------
# Phase 2 — Indeed RSS per country locale (no API key needed)
# ---------------------------------------------------------------------------

def scrape_indeed_intl(term: str, city: str, country: str, log_fn=None) -> List[dict]:
    jobs = []
    locale = INDEED_LOCALES.get(country, "www")
    base   = f"https://{locale}.indeed.com" if locale != "www" else "https://www.indeed.com"
    url = (
        f"{base}/rss?q={requests.utils.quote(term)}"
        f"&l={requests.utils.quote(city)}&sort=date&limit=20"
    )
    try:
        resp = safe_get(url)
        soup = BeautifulSoup(resp.content, "lxml-xml")
        for item in soup.find_all("item")[:20]:
            try:
                title    = item.find("title").get_text(strip=True) if item.find("title") else ""
                link     = item.find("link").get_text(strip=True) if item.find("link") else ""
                desc_raw = item.find("description").get_text(strip=True) if item.find("description") else ""
                desc     = BeautifulSoup(desc_raw, "html.parser").get_text(strip=True)
                src_tag  = item.find("source")
                company  = src_tag.get_text(strip=True) if src_tag else ""
                j = make_job(title, company, city, "", desc, link, "Indeed", country)
                if j:
                    jobs.append(j)
            except Exception:
                continue
        time.sleep(1)
    except Exception as e:
        _log(f"  Indeed RSS ({country}/{city}) error: {e}", log_fn)
    return jobs


# ---------------------------------------------------------------------------
# Phase 3 — Specialist boards (bonus; fail gracefully)
# ---------------------------------------------------------------------------

def _html_board(name, url, card_sel, title_sel, co_sel, loc_sel,
                sal_sel, desc_sel, base_url, country, limit=20, log_fn=None) -> List[dict]:
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
                co = card.select_one(co_sel) if co_sel else None
                lo = card.select_one(loc_sel) if loc_sel else None
                sa = card.select_one(sal_sel) if sal_sel else None
                de = card.select_one(desc_sel) if desc_sel else None
                j = make_job(
                    te.get_text(strip=True),
                    co.get_text(strip=True) if co else "",
                    lo.get_text(strip=True) if lo else country,
                    sa.get_text(strip=True) if sa else "",
                    de.get_text(strip=True) if de else "",
                    job_url, name, country,
                )
                if j:
                    jobs.append(j)
            except Exception:
                continue
        time.sleep(1)
    except Exception as e:
        _log(f"  {name} error: {e}", log_fn)
    return jobs


def scrape_naukri_gulf(term: str, log_fn=None) -> List[dict]:
    """NaukriGulf — UAE’s leading job board, highly reliable for SC roles."""
    url = f"https://www.naukrigulf.com/{term.replace(' ', '-')}-jobs-in-uae"
    return _html_board(
        "NaukriGulf", url,
        "div.ni-job-tuple, article.job-tuple, li.job-tuple",
        "a.title, h2 a, h3 a, .desig a",
        ".comp-name, .company-name, .org-name",
        ".loc span, .location span, .desig-loc",
        ".salary, .sal",
        ".job-desc, .desc",
        "https://www.naukrigulf.com", "UAE", log_fn=log_fn,
    )


def scrape_seek_au(term: str, city: str, log_fn=None) -> List[dict]:
    """SEEK — Australia & New Zealand’s #1 board."""
    country = "New Zealand" if city.lower() in ["auckland", "wellington", "christchurch"] else "Australia"
    base    = "www.seek.co.nz" if country == "New Zealand" else "www.seek.com.au"
    url = f"https://{base}/{term.replace(' ', '-')}-jobs/in-{city.lower().replace(' ', '-')}"
    return _html_board(
        "SEEK", url,
        "article[data-testid='job-card'], div[data-testid='job-card'], article.job-card",
        "a[data-testid='job-title'], h3 a, h2 a, .job-title a",
        "[data-testid='company-name'], .company-name",
        "[data-testid='job-location'], .location",
        "[data-testid='salary'], .salary",
        "[data-testid='job-description'], .description",
        f"https://{base}", country, log_fn=log_fn,
    )


def scrape_jobstreet_sg(term: str, log_fn=None) -> List[dict]:
    """JobStreet — Singapore’s dominant job board."""
    url = f"https://www.jobstreet.com.sg/{term.replace(' ', '-')}-jobs"
    return _html_board(
        "JobStreet SG", url,
        "article[data-testid='job-card'], div[data-card-type='JobCard'], div.job-card",
        "a[data-testid='job-title'], h3 a, h2 a",
        "[data-testid='company-name'], .company-name",
        "[data-testid='job-location'], .location",
        "[data-testid='salary'], .salary",
        ".description, .job-description",
        "https://www.jobstreet.com.sg", "Singapore", log_fn=log_fn,
    )


def scrape_jobbank_canada(term: str, log_fn=None) -> List[dict]:
    """Job Bank Canada — official federal government board, reliable & free."""
    url = (
        f"https://www.jobbank.gc.ca/jobsearch/jobsearch"
        f"?searchstring={requests.utils.quote(term)}&locationstring=Canada"
    )
    return _html_board(
        "Job Bank Canada (Gov)", url,
        "article.resultJobItem, li.results-jobs",
        "h3 a, h2 a, .noctitle a",
        ".business, .employer",
        ".location",
        ".salary",
        ".description",
        "https://www.jobbank.gc.ca", "Canada", log_fn=log_fn,
    )


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def run_scraper_international_as_list(
    keywords: list,
    countries: Optional[List[str]] = None,
    log_fn: Optional[Callable] = None,
) -> List[dict]:
    """
    Lean entry point used by automation_runtime and the FastAPI endpoint.
    - keywords: list of search terms (uses first 2 to avoid rate limits)
    - countries: subset to target, defaults to all
    - Returns a deduplicated, scored list of dicts.
    """
    active_countries = countries or list(COUNTRY_CITIES.keys())
    term = " ".join(keywords[:2]) or "supply chain logistics"
    all_jobs: List[dict] = []

    _log(f"[INTL] Starting international scrape | term='{term}' | countries={active_countries}", log_fn)

    # Phase 1 — Adzuna (reliable API, returns immediately)
    _log("[INTL P1] Adzuna API...", log_fn)
    for country in active_countries:
        jobs = scrape_adzuna_intl(term, country, log_fn)
        _log(f"  Adzuna {country}: {len(jobs)} jobs", log_fn)
        all_jobs += jobs

    # Phase 2 — Indeed RSS per city
    _log("[INTL P2] Indeed RSS...", log_fn)
    for country in active_countries:
        for city in COUNTRY_CITIES.get(country, [country]):
            jobs = scrape_indeed_intl(term, city, country, log_fn)
            _log(f"  Indeed {country}/{city}: {len(jobs)} jobs", log_fn)
            all_jobs += jobs

    # Phase 3 — Specialist boards (best effort)
    _log("[INTL P3] Specialist boards...", log_fn)
    if "UAE" in active_countries:
        all_jobs += scrape_naukri_gulf(term, log_fn)
    if "Singapore" in active_countries:
        all_jobs += scrape_jobstreet_sg(term, log_fn)
    if "Canada" in active_countries:
        all_jobs += scrape_jobbank_canada(term, log_fn)
    for country in ["Australia", "New Zealand"]:
        if country in active_countries:
            for city in COUNTRY_CITIES[country]:
                all_jobs += scrape_seek_au(term, city, log_fn)

    # Dedup
    seen, unique = set(), []
    for j in all_jobs:
        key = (
            j["title"].lower().strip(),
            j.get("company", "").lower().strip(),
            j.get("country", "").lower(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(j)

    # Score + flag visa sponsorship
    for j in unique:
        j["visa_sponsored"] = is_intl_sponsor(j.get("company", ""), j.get("description", ""))
        desc_lower = j.get("description", "").lower()
        if any(sig in desc_lower for sig in [
            "visa sponsorship", "work permit", "relocation", "visa support",
            "sponsorship available", "sponsored",
        ]):
            j["visa_sponsored"] = True
        j["match_score"] = score_job(j)

    unique.sort(key=lambda x: x["match_score"], reverse=True)

    _log(f"[INTL] Done: {len(unique)} unique jobs across {len(active_countries)} countries", log_fn)
    sponsored = sum(1 for j in unique if j.get("visa_sponsored"))
    _log(f"[INTL] Visa/relocation flagged: {sponsored}", log_fn)

    # Save CSV
    try:
        import pandas as pd
        ts  = datetime.now().strftime("%Y%m%d_%H%M")
        out = DATA_DIR / f"jobs_international_{ts}.csv"
        pd.DataFrame(unique).to_csv(out, index=False, encoding="utf-8")
        _log(f"[INTL] Saved: exports/{out.name}", log_fn)
    except Exception:
        pass

    return unique


def run_scraper_international_full(log_fn: Optional[Callable] = None) -> List[dict]:
    """
    Full-depth run — all CORE_TERMS × all countries.
    Called from the Streamlit ‘Deep Scan’ button only.
    """
    all_jobs: List[dict] = []
    total = len(CORE_TERMS)
    for i, term in enumerate(CORE_TERMS, 1):
        _log(f"[INTL FULL] [{i}/{total}] '{term}'", log_fn)
        all_jobs += run_scraper_international_as_list([term], log_fn=log_fn)
        time.sleep(1)

    # Final dedup across all terms
    seen, unique = set(), []
    for j in all_jobs:
        key = (j["title"].lower().strip(), j.get("company", "").lower().strip(), j.get("country", "").lower())
        if key not in seen:
            seen.add(key)
            unique.append(j)

    unique.sort(key=lambda x: x["match_score"], reverse=True)
    _log(f"[INTL FULL] Total unique: {len(unique)}", log_fn)
    return unique
