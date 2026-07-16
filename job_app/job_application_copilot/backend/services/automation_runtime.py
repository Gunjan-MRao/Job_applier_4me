import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

RUNS: Dict[str, dict] = {}
RUN_LOCK = threading.Lock()

JOBSPY_BASE_URL = "http://127.0.0.1:8010"
JOBSPY_SITES = ["linkedin", "indeed", "glassdoor", "google"]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

JOBSPY_PAGE_SIZE = 25
JOBSPY_MAX_PER_SOURCE = 1000
HTML_SOURCE_DEFAULT_CAP = 200
HTML_SOURCE_DEEP_CAP = 500
GLOBAL_HARD_CAP = 5000

GENERAL_HTML_SOURCES = [
    "reed",
    "cvlibrary",
    "totaljobs",
    "jobsite",
    "cwjobs",
    "welcometothejungle",
    "applied",
]

VISA_SOURCES = [
    "ukvisasponsorships",
    "visajobuk",
    "tier2jobs",
    "sponsorshipjobsio",
]

PUBLIC_SECTOR_SOURCES = [
    "findajob",
    "civilservice",
    "nhs",
    "trac",
    "lgjobs",
    "jobsacuk",
]

FALLBACK_JOBS = [
    {
        "title": "Graduate Logistics Coordinator",
        "company": "DHL",
        "location": "United Kingdom",
        "url": "https://example.com/jobs/dhl-logistics-coordinator",
        "sponsorship_status": "yes",
        "description": "Graduate logistics, transport planning, warehouse coordination, supply chain support.",
        "source": "fallback",
    },
    {
        "title": "Supply Chain Analyst",
        "company": "Amazon",
        "location": "United Kingdom",
        "url": "https://example.com/jobs/amazon-supply-chain-analyst",
        "sponsorship_status": "unknown",
        "description": "Supply chain analyst, reporting, Excel, forecasting, planning.",
        "source": "fallback",
    },
    {
        "title": "Operations Planner",
        "company": "Unipart",
        "location": "United Kingdom",
        "url": "https://example.com/jobs/unipart-operations-planner",
        "sponsorship_status": "yes",
        "description": "Operations planning, logistics support, inventory and transport operations.",
        "source": "fallback",
    },
]


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def add_log(run: dict, level: str, message: str) -> None:
    run["logs"].append({"ts": now_iso(), "level": level, "message": message})
    run["logs"] = run["logs"][-1500:]


def update_run(run_id: str, **kwargs) -> None:
    with RUN_LOCK:
        run = RUNS.get(run_id)
        if run:
            run.update(kwargs)


def get_run(run_id: str):
    with RUN_LOCK:
        return RUNS.get(run_id)


def list_runs() -> List[dict]:
    with RUN_LOCK:
        return list(RUNS.values())


def create_run(payload) -> dict:
    run_id = str(uuid.uuid4())
    run = {
        "run_id": run_id,
        "candidate_email": payload.candidate_email,
        "status": "queued",
        "stage": "queued",
        "progress_percent": 0,
        "jobs_scanned": 0,
        "jobs_matched": 0,
        "jobs_applied": 0,
        "jobs_failed": 0,
        "current_url": None,
        "logs": [],
        "result_summary": None,
        "created_at": now_iso(),
    }
    add_log(run, "info", "Automation run created.")
    with RUN_LOCK:
        RUNS[run_id] = run
    return run


def keyword_score(text: str, keywords: List[str]) -> int:
    haystack = (text or "").lower()
    return sum(1 for kw in keywords if kw and kw.strip().lower() in haystack)


def classify_sponsorship(description: str) -> str:
    text = (description or "").lower()

    positive = [
        "visa sponsorship",
        "sponsorship available",
        "skilled worker visa",
        "certificate of sponsorship",
        "cos available",
        "we can sponsor",
        "eligible for sponsorship",
        "sponsorship may be available",
    ]
    negative = [
        "no sponsorship",
        "unable to sponsor",
        "must have right to work",
        "no visa sponsorship",
        "cannot sponsor",
        "not able to sponsor",
        "you must already have the right to work",
        "right to work in the uk",
        "without sponsorship",
    ]

    if any(x in text for x in negative):
        return "no"
    if any(x in text for x in positive):
        return "yes"
    return "unknown"


def normalize_text(value) -> str:
    return (value or "").strip()


def make_job(title: str, company: str, location: str, salary: str, description: str, job_url: str, source: str) -> dict | None:
    title = normalize_text(title)
    if not title:
        return None

    desc = normalize_text(description)
    salary = normalize_text(salary)

    return {
        "title": title,
        "company": normalize_text(company) or "Unknown company",
        "location": normalize_text(location) or "United Kingdom",
        "salary": salary,
        "url": normalize_text(job_url),
        "sponsorship_status": classify_sponsorship(desc),
        "description": desc or title,
        "source": source,
    }


def normalize_jobspy_row(row: dict) -> dict:
    description = row.get("description") or ""
    return {
        "title": row.get("title") or "Unknown title",
        "company": row.get("company") or "Unknown company",
        "location": row.get("location") or "United Kingdom",
        "salary": row.get("min_amount") or row.get("max_amount") or "",
        "url": row.get("job_url") or "",
        "sponsorship_status": classify_sponsorship(description),
        "description": description,
        "source": row.get("site") or "jobspy",
        "date_posted": row.get("date_posted"),
        "job_type": row.get("job_type"),
        "is_remote": row.get("is_remote"),
    }


def dedupe_jobs(jobs: List[dict]) -> List[dict]:
    seen = set()
    unique = []

    for job in jobs:
        key = (
            (job.get("title") or "").strip().lower(),
            (job.get("company") or "").strip().lower(),
            (job.get("url") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)

    return unique


def safe_get(url: str, run: dict, timeout: tuple = (5, 20)):
    return requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)


def search_jobspy_site_paged(site_name: str, keywords: List[str], location: str, target_jobs: int, run: dict) -> List[dict]:
    search_term = " ".join(keywords).strip() or "logistics supply chain"
    collected = []
    offset = 0
    no_growth_rounds = 0
    source_cap = min(target_jobs, JOBSPY_MAX_PER_SOURCE)

    while len(collected) < source_cap and no_growth_rounds < 3:
        batch_size = min(JOBSPY_PAGE_SIZE, source_cap - len(collected))
        params = {
            "site_name": site_name,
            "search_term": search_term,
            "location": location or "United Kingdom",
            "results_wanted": batch_size,
            "offset": offset,
        }

        try:
            add_log(run, "info", f"Querying JobSpy source={site_name} offset={offset} batch={batch_size}")
            resp = requests.get(f"{JOBSPY_BASE_URL}/search_jobs", params=params, timeout=(5, 120))

            if resp.status_code != 200:
                add_log(run, "warning", f"JobSpy source={site_name} returned status {resp.status_code}")
                break

            rows = resp.json().get("results", [])
            normalized = [normalize_jobspy_row(r) for r in rows]

            before = len(collected)
            collected.extend(normalized)
            collected = dedupe_jobs(collected)
            gained = len(collected) - before

            add_log(run, "info", f"JobSpy source={site_name} returned {len(rows)} rows, gained {gained}, total={len(collected)}")

            if not rows:
                add_log(run, "info", f"JobSpy source={site_name} exhausted at offset={offset}")
                break

            no_growth_rounds = no_growth_rounds + 1 if gained == 0 else 0
            offset += JOBSPY_PAGE_SIZE
            time.sleep(1.0)
        except requests.exceptions.Timeout:
            add_log(run, "warning", f"JobSpy source={site_name} timed out at offset={offset}")
            break
        except Exception as exc:
            add_log(run, "warning", f"JobSpy source={site_name} failed at offset={offset}: {exc}")
            break

    return collected


def extract_cards(soup: BeautifulSoup, selectors: List[str]):
    for selector in selectors:
        nodes = soup.select(selector)
        if nodes:
            return nodes
    return []


def text_or_none(node, selectors: List[str]) -> str:
    if not node:
        return ""
    for selector in selectors:
        el = node.select_one(selector)
        if el:
            return el.get_text(" ", strip=True)
    return ""


def href_or_none(node, selectors: List[str]) -> str:
    if not node:
        return ""
    for selector in selectors:
        el = node.select_one(selector)
        if el and el.get("href"):
            return el.get("href").strip()
    return ""


def collect_html_jobs(run: dict, source_name: str, url: str, card_selectors: List[str], title_selectors: List[str],
                      company_selectors: List[str], location_selectors: List[str], salary_selectors: List[str],
                      desc_selectors: List[str], base_url: str, limit: int) -> List[dict]:
    jobs = []
    try:
        add_log(run, "info", f"Fetching {source_name} listings from {url}")
        resp = safe_get(url, run)
        if resp.status_code != 200:
            add_log(run, "warning", f"{source_name} returned status {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = extract_cards(soup, card_selectors)
        add_log(run, "info", f"{source_name} parsing found {len(cards)} candidate cards")

        seen = set()
        for card in cards:
            title = text_or_none(card, title_selectors)
            href = href_or_none(card, title_selectors)
            if not title or not href:
                continue

            job_url = href if href.startswith("http") else f"{base_url}{href}"
            if job_url in seen:
                continue
            seen.add(job_url)

            job = make_job(
                title=title,
                company=text_or_none(card, company_selectors),
                location=text_or_none(card, location_selectors),
                salary=text_or_none(card, salary_selectors),
                description=text_or_none(card, desc_selectors) or card.get_text(" ", strip=True),
                job_url=job_url,
                source=source_name,
            )
            if job:
                jobs.append(job)

            if len(jobs) >= limit:
                break

        jobs = dedupe_jobs(jobs)
        add_log(run, "info", f"{source_name} returned {len(jobs)} normalized jobs")
        return jobs
    except requests.exceptions.Timeout:
        add_log(run, "warning", f"{source_name} fetch timed out")
        return []
    except Exception as exc:
        add_log(run, "warning", f"{source_name} fetch failed: {exc}")
        return []


def fetch_reed_jobs(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    loc = quote_plus(location or "united kingdom")
    url = f"https://www.reed.co.uk/jobs/{q}-jobs-in-{loc}"
    return collect_html_jobs(
        run, "reed", url,
        ["article"],
        ["h2 a", "h3 a", "a[href*='/jobs/']"],
        [".posted-by", ".recruiter-name", ".company"],
        [".location", ".distance", ".job-metadata__item"],
        [".salary", ".job-metadata__item"],
        [".description", ".job-result-description"],
        "https://www.reed.co.uk",
        limit,
    )


def fetch_cvlibrary_jobs(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    loc = quote_plus(location or "United Kingdom")
    url = f"https://www.cv-library.co.uk/search-jobs?keywords={q}&geo={loc}"
    return collect_html_jobs(
        run, "cvlibrary", url,
        ["li.job", "article.job", ".job-result"],
        ["h2 a", "h3 a", ".job__title a", "a.job-title"],
        [".company", ".job-company", ".employer"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".description", ".job-description", ".summary"],
        "https://www.cv-library.co.uk",
        limit,
    )


def fetch_totaljobs_jobs(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    q = "-".join((" ".join(keywords).strip() or "logistics supply chain").split())
    loc = "-".join((location or "united kingdom").split())
    url = f"https://www.totaljobs.com/jobs/{q}/in-{loc}"
    return collect_html_jobs(
        run, "totaljobs", url,
        ["article", ".job-result", ".job-card"],
        ["h2 a", "h3 a", ".job-title a"],
        [".company", ".company-name", ".recruiter"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".description", ".summary", ".job-description"],
        "https://www.totaljobs.com",
        limit,
    )


def fetch_jobsite_jobs(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    q = "-".join((" ".join(keywords).strip() or "logistics supply chain").split())
    loc = "-".join((location or "united kingdom").split())
    url = f"https://www.jobsite.co.uk/jobs/{q}/in-{loc}"
    return collect_html_jobs(
        run, "jobsite", url,
        ["article", ".job-result-item", ".job-card"],
        ["h2 a", "h3 a", ".job-title a"],
        [".recruiter", ".company-name", ".company"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".job-description", ".summary"],
        "https://www.jobsite.co.uk",
        limit,
    )


def fetch_cwjobs_jobs(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    q = "-".join((" ".join(keywords).strip() or "logistics supply chain").split())
    loc = "-".join((location or "united kingdom").split())
    url = f"https://www.cwjobs.co.uk/jobs/{q}/in-{loc}"
    return collect_html_jobs(
        run, "cwjobs", url,
        ["article", ".job-result-item", ".job-card"],
        ["h2 a", "h3 a", ".job-title a"],
        [".recruiter", ".company-name", ".company"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".job-description", ".summary"],
        "https://www.cwjobs.co.uk",
        limit,
    )


def fetch_welcome_to_the_jungle_jobs(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://uk.welcometothejungle.com/jobs?query={q}"
    return collect_html_jobs(
        run, "welcometothejungle", url,
        ["article", "[data-testid='search-results-item']", ".sc-beqWaB"],
        ["h2 a", "h3 a", "a[href*='/jobs/']"],
        [".company", "[data-testid='company-name']", ".sc-gueYoa"],
        [".location", "[data-testid='job-location']"],
        [".salary", "[data-testid='job-salary']"],
        [".description", "[data-testid='job-description']"],
        "https://uk.welcometothejungle.com",
        limit,
    )


def fetch_applied_jobs(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://app.beapplied.com/job-board/?q={q}"
    return collect_html_jobs(
        run, "applied", url,
        ["article", ".job-card", ".job-listing", ".vacancy"],
        ["h2 a", "h3 a", ".job-title a", "a[href*='/job/']"],
        [".company", ".employer", ".organisation"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".description", ".summary"],
        "https://app.beapplied.com",
        limit,
    )


def fetch_ukvisasponsorships_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://ukvisasponsorships.co.uk/jobs?q={q}"
    return collect_html_jobs(
        run, "ukvisasponsorships", url,
        ["div.job", "article", "li.vacancy", ".job-card", ".job-listing"],
        ["h2 a", "h3 a", ".title a", ".job-title a", "a"],
        [".company", ".employer", ".trust"],
        [".location"],
        [".salary"],
        [".description", ".summary"],
        "https://ukvisasponsorships.co.uk",
        limit,
    )


def fetch_visajobuk_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://visajob.co.uk/jobs?q={q}&country=UK"
    return collect_html_jobs(
        run, "visajobuk", url,
        ["div.job-card", "article.job", "li.job", ".vacancy", ".job"],
        ["h2 a", "h3 a", ".job-title a", "a.title", "a"],
        [".company", ".employer", ".organisation"],
        [".location"],
        [".salary"],
        [".description", ".summary"],
        "https://visajob.co.uk",
        limit,
    )


def fetch_tier2jobs_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://www.tier2jobs.co.uk/jobs?q={q}"
    return collect_html_jobs(
        run, "tier2jobs", url,
        ["div.job", "li.job", "article", ".job-listing", ".job-card"],
        ["h2 a", "h3 a", ".title a", ".job-title a", "a"],
        [".company", ".employer"],
        [".location"],
        [".salary"],
        [".description", ".summary"],
        "https://www.tier2jobs.co.uk",
        limit,
    )


def fetch_sponsorshipjobsio_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://sponsorshipjobs.io/jobs?q={q}&country=uk"
    return collect_html_jobs(
        run, "sponsorshipjobsio", url,
        ["div.job", "article.job", "li.job-item", ".job-card", ".vacancy"],
        ["h2 a", "h3 a", ".job-title a", ".title a", "a"],
        [".company", ".employer"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".description", ".summary", ".job-description"],
        "https://sponsorshipjobs.io",
        limit,
    )


def fetch_findajob_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://findajob.dwp.gov.uk/search?q={q}&where=UnitedKingdom&pp=25"
    return collect_html_jobs(
        run, "findajob", url,
        ["div.search-result", "li.search-result", "article.search-result"],
        ["h3 a", "h2 a", ".job-title a", "a"],
        [".employer", ".company", "dd"],
        [".location", ".address"],
        [".salary", ".pay"],
        [".description", ".snippet", "p"],
        "https://findajob.dwp.gov.uk",
        limit,
    )


def fetch_civil_service_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = (
        "https://www.civilservicejobs.service.gov.uk/csr/jobs.cgi"
        f"?jcode=&page_action=search_by_keyword&keyword={q}&sort=closingdate"
    )
    return collect_html_jobs(
        run, "civilservice", url,
        ["li.search-results-job-box", "div.job-result", ".search-results-job"],
        ["h3 a", "h2 a", ".job-title a", "a[href*='job.cgi']"],
        [".organisation", ".employer", ".department"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".description", ".summary"],
        "https://www.civilservicejobs.service.gov.uk",
        limit,
    )


def fetch_nhs_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://www.jobs.nhs.uk/candidate/search/results?keyword={q}&location=United%20Kingdom&distance=200"
    return collect_html_jobs(
        run, "nhs", url,
        ["li.vacancy", "div.vacancy-item", "article", ".nhsuk-card"],
        ["h2 a", "h3 a", ".vacancy-title a", "a[href*='/candidate/jobadvert/']"],
        [".employer", ".organisation", ".trust-name"],
        [".location", ".vacancy-location"],
        [".salary", ".pay-scheme", ".vacancy-salary"],
        [".description", ".vacancy-description", ".summary"],
        "https://www.jobs.nhs.uk",
        limit,
    )


def fetch_trac_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://www.trac.jobs/jobs/search?keywords={q}&location=UnitedKingdom"
    return collect_html_jobs(
        run, "trac", url,
        ["div.job-result", "li.job", "article", ".job-listing"],
        ["h2 a", "h3 a", ".job-title a", "a"],
        [".employer", ".trust", ".organisation"],
        [".location"],
        [".salary"],
        [".description", ".summary"],
        "https://www.trac.jobs",
        limit,
    )


def fetch_lgjobs_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://www.lgjobs.com/vacancies?keywords={q}&location=UnitedKingdom&distance=200"
    return collect_html_jobs(
        run, "lgjobs", url,
        ["li.vacancy", "div.vacancy", "article.vacancy", ".vacancy-item"],
        ["h2 a", "h3 a", ".vacancy-title a", "a[href*='vacancy']"],
        [".organisation", ".employer", ".council"],
        [".location"],
        [".salary"],
        [".description", ".summary"],
        "https://www.lgjobs.com",
        limit,
    )


def fetch_jobsacuk_jobs(keywords: List[str], limit: int, run: dict) -> List[dict]:
    q = quote_plus(" ".join(keywords).strip() or "logistics supply chain")
    url = f"https://www.jobs.ac.uk/search/?keywords={q}&location=United+Kingdom&distance=200"
    return collect_html_jobs(
        run, "jobsacuk", url,
        ["div.r-item", "li.job", "article.job", ".job-result"],
        ["h2 a", "h3 a", ".title a", "a.job-title"],
        [".employer", ".institution", ".university"],
        [".location"],
        [".salary"],
        [".description", ".summary"],
        "https://www.jobs.ac.uk",
        limit,
    )


def fetch_general_html_sources(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    jobs = []
    fetchers = [
        lambda: fetch_reed_jobs(keywords, location, limit, run),
        lambda: fetch_cvlibrary_jobs(keywords, location, limit, run),
        lambda: fetch_totaljobs_jobs(keywords, location, limit, run),
        lambda: fetch_jobsite_jobs(keywords, location, limit, run),
        lambda: fetch_cwjobs_jobs(keywords, location, limit, run),
        lambda: fetch_welcome_to_the_jungle_jobs(keywords, location, limit, run),
        lambda: fetch_applied_jobs(keywords, location, limit, run),
    ]

    for fetcher in fetchers:
        rows = fetcher()
        jobs.extend(rows)
        jobs = dedupe_jobs(jobs)
        add_log(run, "info", f"General HTML sources combined unique jobs={len(jobs)}")
        if len(jobs) >= GLOBAL_HARD_CAP:
            return jobs[:GLOBAL_HARD_CAP]

    return jobs


def fetch_visa_sources(keywords: List[str], limit: int, run: dict) -> List[dict]:
    jobs = []
    fetchers = [
        lambda: fetch_ukvisasponsorships_jobs(keywords, limit, run),
        lambda: fetch_visajobuk_jobs(keywords, limit, run),
        lambda: fetch_tier2jobs_jobs(keywords, limit, run),
        lambda: fetch_sponsorshipjobsio_jobs(keywords, limit, run),
    ]

    for fetcher in fetchers:
        rows = fetcher()
        jobs.extend(rows)
        jobs = dedupe_jobs(jobs)
        add_log(run, "info", f"Visa sources combined unique jobs={len(jobs)}")
        if len(jobs) >= GLOBAL_HARD_CAP:
            return jobs[:GLOBAL_HARD_CAP]

    return jobs


def fetch_public_sector_sources(keywords: List[str], limit: int, run: dict) -> List[dict]:
    jobs = []
    fetchers = [
        lambda: fetch_findajob_jobs(keywords, limit, run),
        lambda: fetch_civil_service_jobs(keywords, limit, run),
        lambda: fetch_nhs_jobs(keywords, limit, run),
        lambda: fetch_trac_jobs(keywords, limit, run),
        lambda: fetch_lgjobs_jobs(keywords, limit, run),
        lambda: fetch_jobsacuk_jobs(keywords, limit, run),
    ]

    for fetcher in fetchers:
        rows = fetcher()
        jobs.extend(rows)
        jobs = dedupe_jobs(jobs)
        add_log(run, "info", f"Public sector sources combined unique jobs={len(jobs)}")
        if len(jobs) >= GLOBAL_HARD_CAP:
            return jobs[:GLOBAL_HARD_CAP]

    return jobs


def get_real_jobs(keywords: List[str], location: str, max_jobs: int, run: dict) -> List[dict]:
    all_jobs = []

    deep_crawl = max_jobs <= 0
    requested_total = GLOBAL_HARD_CAP if deep_crawl else max(max_jobs, 50)
    html_limit = HTML_SOURCE_DEEP_CAP if deep_crawl else min(requested_total, HTML_SOURCE_DEFAULT_CAP)
    jobspy_target = JOBSPY_MAX_PER_SOURCE if deep_crawl else min(max(requested_total, 50), JOBSPY_MAX_PER_SOURCE)

    add_log(
        run,
        "info",
        f"Search mode={'deep_crawl' if deep_crawl else 'bounded'} requested_total={requested_total} "
        f"jobspy_target={jobspy_target} html_limit={html_limit}",
    )

    for site in JOBSPY_SITES:
        site_jobs = search_jobspy_site_paged(site, keywords, location, jobspy_target, run)
        all_jobs.extend(site_jobs)
        all_jobs = dedupe_jobs(all_jobs)
        add_log(run, "info", f"After JobSpy source={site}, combined unique jobs={len(all_jobs)}")
        if len(all_jobs) >= GLOBAL_HARD_CAP:
            return all_jobs[:GLOBAL_HARD_CAP]

    general_jobs = fetch_general_html_sources(keywords, location, html_limit, run)
    all_jobs.extend(general_jobs)
    all_jobs = dedupe_jobs(all_jobs)
    add_log(run, "info", f"After general HTML sources, combined unique jobs={len(all_jobs)}")
    if len(all_jobs) >= GLOBAL_HARD_CAP:
        return all_jobs[:GLOBAL_HARD_CAP]

    visa_jobs = fetch_visa_sources(keywords, html_limit, run)
    all_jobs.extend(visa_jobs)
    all_jobs = dedupe_jobs(all_jobs)
    add_log(run, "info", f"After visa sources, combined unique jobs={len(all_jobs)}")
    if len(all_jobs) >= GLOBAL_HARD_CAP:
        return all_jobs[:GLOBAL_HARD_CAP]

    public_jobs = fetch_public_sector_sources(keywords, html_limit, run)
    all_jobs.extend(public_jobs)
    all_jobs = dedupe_jobs(all_jobs)
    add_log(run, "info", f"After public sector sources, combined unique jobs={len(all_jobs)}")

    if all_jobs:
        add_log(run, "info", f"Combined multi-source search produced {len(all_jobs)} unique jobs")
        return all_jobs[:GLOBAL_HARD_CAP] if deep_crawl else all_jobs[:requested_total]

    add_log(run, "warning", "No live jobs found from active sources. Using fallback sample jobs.")
    fallback = []
    for item in FALLBACK_JOBS:
        clone = dict(item)
        clone["location"] = location or clone["location"]
        fallback.append(clone)
    return fallback


def run_automation_pipeline(run_id: str, payload) -> None:
    run = get_run(run_id)
    if not run:
        return

    try:
        update_run(run_id, status="running", stage="loading_profile", progress_percent=5)
        add_log(run, "info", f"Loading candidate profile for {payload.candidate_email}")
        time.sleep(0.5)

        update_run(run_id, stage="searching_jobs", progress_percent=15)
        add_log(run, "info", f"Searching jobs for keywords={payload.keywords} in {payload.location}")

        jobs = get_real_jobs(payload.keywords, payload.location, payload.max_jobs, run)

        matched_jobs = []
        total = max(len(jobs), 1)

        for idx, job in enumerate(jobs, start=1):
            run = get_run(run_id)
            if not run:
                return

            update_run(
                run_id,
                stage="screening_jobs",
                current_url=job.get("url"),
                jobs_scanned=idx,
                progress_percent=min(20 + int((idx / total) * 40), 60),
            )

            title = job.get("title", "")
            company = job.get("company", "")
            desc = job.get("description", "")
            source = job.get("source", "unknown")
            combined_text = f"{title} {company} {desc}"

            score = keyword_score(combined_text, payload.keywords)
            sponsorship_status = job.get("sponsorship_status", "unknown")

            add_log(run, "info", f"Screening {title} at {company} from {source}")
            time.sleep(0.01)

            if score > 0 and sponsorship_status != "no":
                matched_jobs.append({**job, "match_score": score})
                update_run(run_id, jobs_matched=len(matched_jobs))
                add_log(run, "info", f"Matched: {title} at {company} (score={score}, sponsorship={sponsorship_status})")
            else:
                reason = []
                if score <= 0:
                    reason.append("no keyword match")
                if sponsorship_status == "no":
                    reason.append("explicit no sponsorship")
                if not reason:
                    reason.append("filtered")
                add_log(run, "warning", f"Skipped: {title} at {company} ({', '.join(reason)})")

        update_run(run_id, stage="applying", progress_percent=70, current_url=None)
        add_log(run, "info", f"Starting apply phase for {len(matched_jobs)} matched jobs.")
        time.sleep(0.25)

        applied = 0
        failed = 0

        for idx, job in enumerate(matched_jobs, start=1):
            run = get_run(run_id)
            if not run:
                return

            update_run(
                run_id,
                stage="applying",
                current_url=job.get("url"),
                progress_percent=min(70 + int((idx / max(len(matched_jobs), 1)) * 20), 95),
            )

            title = job.get("title", "")
            company = job.get("company", "")

            add_log(run, "info", f"Opening application flow for {title} at {company}")
            time.sleep(0.02)

            if payload.auto_apply:
                applied += 1
                update_run(run_id, jobs_applied=applied)
                add_log(run, "info", f"Recorded apply-ready result for {title} at {company}")
            else:
                failed += 1
                update_run(run_id, jobs_failed=failed)
                add_log(run, "warning", f"Auto-apply disabled for {title} at {company}")

        summary = {
            "keywords": payload.keywords,
            "location": payload.location,
            "requested_jobs": payload.max_jobs,
            "deep_crawl": payload.max_jobs <= 0,
            "jobs_seen": len(jobs),
            "matched_jobs": len(matched_jobs),
            "applied_jobs": applied,
            "failed_jobs": failed,
            "mode": "maximum-possible-scrape-expanded-uk",
            "jobspy_sources": JOBSPY_SITES,
            "general_html_sources": GENERAL_HTML_SOURCES,
            "visa_sources": VISA_SOURCES,
            "public_sector_sources": PUBLIC_SECTOR_SOURCES,
            "global_hard_cap": GLOBAL_HARD_CAP,
        }

        update_run(
            run_id,
            status="completed",
            stage="completed",
            progress_percent=100,
            current_url=None,
            result_summary=summary,
        )
        add_log(run, "info", "Automation run completed successfully.")
    except Exception as exc:
        run = get_run(run_id)
        if run:
            update_run(run_id, status="failed", stage="failed", current_url=None)
            add_log(run, "error", f"Automation run failed: {exc}")


def start_run_thread(payload) -> dict:
    run = create_run(payload)
    t = threading.Thread(target=run_automation_pipeline, args=(run["run_id"], payload), daemon=True)
    t.start()
    return run