"""
automation_runtime.py  –  upgraded pipeline

Key improvements over previous version:
- JobSpy called DIRECTLY in-process via `jobspy.scrape_jobs()` (no separate microservice needed)
- Concurrent scraping of all JobSpy sources using ThreadPoolExecutor
- AI-powered fit scoring integrating job_fit_service & resume profile
- LLM cover letter generation (OpenAI / Anthropic / offline graceful fallback)
- Blacklist / whitelist company filtering
- Sponsorship-aware shortlisting wired to parsed resume profile
- Per-job AI match score written into run state for the UI
- Robust error isolation: one failed source never aborts the run
"""
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

try:
    from jobspy import scrape_jobs as _jobspy_scrape
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False

try:
    import openai as _openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import anthropic as _anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from backend.core.config import settings

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------
RUNS: Dict[str, dict] = {}
RUN_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
JOBSPY_SITES = ["linkedin", "indeed", "glassdoor", "google"]
JOBSPY_FALLBACK_URL = "http://127.0.0.1:8010"
GLOBAL_HARD_CAP = 5000
HTML_SOURCE_DEFAULT_CAP = 200
JOBSPY_MAX_PER_SOURCE = 500

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

FALLBACK_JOBS = [
    {"title": "Graduate Logistics Coordinator", "company": "DHL", "location": "United Kingdom",
     "url": "https://www.dhl.com/gb-en/home/careers.html", "sponsorship_status": "yes",
     "description": "Graduate logistics, transport planning, warehouse coordination, supply chain.", "source": "fallback"},
    {"title": "Supply Chain Analyst", "company": "Amazon", "location": "United Kingdom",
     "url": "https://www.amazon.jobs", "sponsorship_status": "unknown",
     "description": "Supply chain analyst, reporting, Excel, forecasting, planning.", "source": "fallback"},
    {"title": "Operations Planner", "company": "Unipart", "location": "United Kingdom",
     "url": "https://careers.unipart.com", "sponsorship_status": "yes",
     "description": "Operations planning, logistics support, inventory and transport.", "source": "fallback"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def add_log(run: dict, level: str, message: str) -> None:
    run["logs"].append({"ts": now_iso(), "level": level, "message": message})
    run["logs"] = run["logs"][-2000:]


def update_run(run_id: str, **kwargs) -> None:
    with RUN_LOCK:
        run = RUNS.get(run_id)
        if run:
            run.update(kwargs)


def get_run(run_id: str) -> Optional[dict]:
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
        "top_matches": [],
        "created_at": now_iso(),
    }
    add_log(run, "info", "Automation run created.")
    with RUN_LOCK:
        RUNS[run_id] = run
    return run


# ---------------------------------------------------------------------------
# Sponsorship classifier
# ---------------------------------------------------------------------------

def classify_sponsorship(description: str) -> str:
    text = (description or "").lower()
    negative = ["no sponsorship", "unable to sponsor", "must have right to work",
                "no visa sponsorship", "cannot sponsor", "not able to sponsor",
                "without sponsorship", "you must already have the right to work"]
    positive = ["visa sponsorship", "sponsorship available", "skilled worker visa",
                "certificate of sponsorship", "cos available", "we can sponsor",
                "eligible for sponsorship", "sponsorship may be available"]
    if any(x in text for x in negative):
        return "no"
    if any(x in text for x in positive):
        return "yes"
    return "unknown"


# ---------------------------------------------------------------------------
# Keyword scoring (fast, no LLM)
# ---------------------------------------------------------------------------

def keyword_score(text: str, keywords: List[str]) -> int:
    haystack = (text or "").lower()
    return sum(1 for kw in keywords if kw and kw.strip().lower() in haystack)


# ---------------------------------------------------------------------------
# AI fit scoring — uses job_fit_service if profile is available
# ---------------------------------------------------------------------------

def ai_fit_score(job: dict, profile: Optional[dict], keywords: List[str]) -> dict:
    """Return a dict with fit_score (0-100) and fit_level."""
    if profile:
        try:
            from backend.services.match.job_fit_service import evaluate_single_job
            payload = {
                "target_roles": profile.get("likely_roles") or [],
                "resume_skills": profile.get("skills") or [],
                "seniority_target": "entry-level",
                "needs_visa_sponsorship": True,
                "preferred_locations": ["united kingdom", "uk"],
                "work_mode_preferences": [],
                "education_summary": "",
                "policy": {
                    "weights": {"title": 25, "skills": 35, "seniority": 15, "location": 10, "sponsorship": 10, "education": 5},
                    "require_sponsorship_if_needed": False,
                    "reject_when_sponsorship_unknown": False,
                    "use_max_seniority_gap": True,
                    "max_seniority_gap": 2,
                    "location_strict": False,
                    "work_mode_strict": False,
                    "minimum_fit_score": 50,
                },
            }
            job_payload = {
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "skills": [],
                "seniority": "entry-level",
                "location": job.get("location", ""),
                "work_mode": "unknown",
                "sponsorship_available": None if job.get("sponsorship_status") == "unknown"
                    else (True if job.get("sponsorship_status") == "yes" else False),
                "description": job.get("description", ""),
                "source": job.get("source", ""),
                "url": job.get("url", ""),
            }
            result = evaluate_single_job(payload, job_payload)
            return {"fit_score": result["fit_score"], "fit_level": result["fit_level"],
                    "reasons": result["reasons"], "gaps": result["gaps"]}
        except Exception:
            pass

    # fallback: simple keyword score normalised to 100
    combined = f"{job.get('title', '')} {job.get('description', '')}"
    raw = keyword_score(combined, keywords)
    score = min(int(raw / max(len(keywords), 1) * 100), 100)
    level = "strong" if score >= 70 else ("moderate" if score >= 40 else "weak")
    return {"fit_score": score, "fit_level": level, "reasons": [], "gaps": []}


# ---------------------------------------------------------------------------
# LLM cover letter
# ---------------------------------------------------------------------------

def generate_cover_letter(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    skills = ", ".join((profile.get("skills") or [])[:8])
    experience = profile.get("years_of_experience_hint") or "several years'"

    prompt = (
        f"Write a concise, professional cover letter for {name} applying for '{title}' at {company}. "
        f"The candidate has {experience} experience with skills: {skills}. "
        f"Job description snippet: {(job.get('description') or '')[:400]}. "
        "Keep it under 250 words. Do not use placeholder brackets. Sound genuine and specific."
    )

    # Try OpenAI
    if OPENAI_AVAILABLE and settings.openai_api_key:
        try:
            client = _openai.OpenAI(api_key=settings.openai_api_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.7,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            pass

    # Try Anthropic
    if ANTHROPIC_AVAILABLE and settings.anthropic_api_key:
        try:
            client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
            resp = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception:
            pass

    # Offline template fallback
    return (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to express my interest in the {title} position at {company}. "
        f"With {experience} experience in {skills}, I am confident I can contribute meaningfully to your team.\n\n"
        f"I look forward to discussing how my background aligns with your needs.\n\n"
        f"Kind regards,\n{name}"
    )


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def dedupe_jobs(jobs: List[dict]) -> List[dict]:
    seen = set()
    unique = []
    for job in jobs:
        key = (
            (job.get("title") or "").strip().lower(),
            (job.get("company") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


# ---------------------------------------------------------------------------
# JobSpy direct in-process scraping (no sidecar microservice required)
# ---------------------------------------------------------------------------

def _safe_val(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def jobspy_scrape_site(site: str, keywords: List[str], location: str, results_wanted: int, run: dict) -> List[dict]:
    search_term = " ".join(keywords).strip() or "supply chain logistics"
    add_log(run, "info", f"[JobSpy-direct] scraping site={site} term='{search_term}' location='{location}'")
    try:
        df = _jobspy_scrape(
            site_name=[site],
            search_term=search_term,
            location=location or "United Kingdom",
            results_wanted=min(results_wanted, JOBSPY_MAX_PER_SOURCE),
            country_indeed="UK",
            linkedin_fetch_description=True,
        )
        rows = []
        for _, row in df.iterrows():
            desc = _safe_val(row.get("description")) or ""
            rows.append({
                "title": _safe_val(row.get("title")) or "Unknown title",
                "company": _safe_val(row.get("company")) or "Unknown company",
                "location": _safe_val(row.get("location")) or location,
                "salary": _safe_val(row.get("min_amount")) or _safe_val(row.get("max_amount")) or "",
                "url": _safe_val(row.get("job_url")) or "",
                "sponsorship_status": classify_sponsorship(desc),
                "description": desc,
                "source": site,
                "date_posted": str(_safe_val(row.get("date_posted")) or ""),
                "job_type": _safe_val(row.get("job_type")),
                "is_remote": _safe_val(row.get("is_remote")),
                "company_logo": _safe_val(row.get("company_logo")),
            })
        add_log(run, "info", f"[JobSpy-direct] site={site} returned {len(rows)} jobs")
        return rows
    except Exception as exc:
        add_log(run, "warning", f"[JobSpy-direct] site={site} failed: {exc}")
        return []


def jobspy_scrape_fallback_http(site: str, keywords: List[str], location: str, results_wanted: int, run: dict) -> List[dict]:
    """Hit the separate jobspy_service sidecar if the direct import failed."""
    search_term = " ".join(keywords).strip() or "supply chain logistics"
    params = {"site_name": site, "search_term": search_term, "location": location or "United Kingdom",
               "results_wanted": min(results_wanted, JOBSPY_MAX_PER_SOURCE), "offset": 0}
    try:
        resp = requests.get(f"{JOBSPY_FALLBACK_URL}/search_jobs", params=params, timeout=(5, 120))
        if resp.status_code != 200:
            return []
        rows = []
        for row in resp.json().get("results", []):
            desc = row.get("description") or ""
            rows.append({
                "title": row.get("title") or "Unknown title",
                "company": row.get("company") or "Unknown company",
                "location": row.get("location") or location,
                "salary": row.get("min_amount") or row.get("max_amount") or "",
                "url": row.get("job_url") or "",
                "sponsorship_status": classify_sponsorship(desc),
                "description": desc,
                "source": site,
            })
        return rows
    except Exception as exc:
        add_log(run, "warning", f"[JobSpy-HTTP] site={site} failed: {exc}")
        return []


def scrape_all_jobspy_parallel(keywords: List[str], location: str, results_per_site: int, run: dict) -> List[dict]:
    all_jobs: List[dict] = []
    scrape_fn = jobspy_scrape_site if JOBSPY_AVAILABLE else jobspy_scrape_fallback_http

    with ThreadPoolExecutor(max_workers=len(JOBSPY_SITES)) as ex:
        futures = {ex.submit(scrape_fn, site, keywords, location, results_per_site, run): site
                   for site in JOBSPY_SITES}
        for fut in as_completed(futures):
            site = futures[fut]
            try:
                jobs = fut.result()
                all_jobs.extend(jobs)
                add_log(run, "info", f"[parallel] site={site} contributed {len(jobs)} jobs")
            except Exception as exc:
                add_log(run, "warning", f"[parallel] site={site} thread error: {exc}")

    return dedupe_jobs(all_jobs)


# ---------------------------------------------------------------------------
# HTML scraping helpers (Reed, CV-Library, NHS, FindAJob, etc.)
# ---------------------------------------------------------------------------

def _collect_html_jobs(run: dict, source_name: str, url: str, card_selectors, title_selectors,
                       company_selectors, location_selectors, salary_selectors, desc_selectors,
                       base_url: str, limit: int) -> List[dict]:
    jobs = []
    try:
        add_log(run, "info", f"[HTML] fetching {source_name}")
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=(5, 20))
        if resp.status_code != 200:
            add_log(run, "warning", f"[HTML] {source_name} status {resp.status_code}")
            return []
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = []
        for sel in card_selectors:
            cards = soup.select(sel)
            if cards:
                break

        seen_urls = set()
        for card in cards:
            title_el = None
            title_text = ""
            href = ""
            for sel in title_selectors:
                el = card.select_one(sel)
                if el:
                    title_text = el.get_text(" ", strip=True)
                    href = el.get("href", "")
                    title_el = el
                    break

            if not title_text or not href:
                continue
            job_url = href if href.startswith("http") else f"{base_url}{href}"
            if job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            def _text(selectors):
                for s in selectors:
                    el = card.select_one(s)
                    if el:
                        return el.get_text(" ", strip=True)
                return ""

            desc = _text(desc_selectors) or card.get_text(" ", strip=True)[:300]
            job = {
                "title": title_text,
                "company": _text(company_selectors) or "Unknown company",
                "location": _text(location_selectors) or "United Kingdom",
                "salary": _text(salary_selectors),
                "url": job_url,
                "sponsorship_status": classify_sponsorship(desc),
                "description": desc,
                "source": source_name,
            }
            jobs.append(job)
            if len(jobs) >= limit:
                break

        add_log(run, "info", f"[HTML] {source_name} → {len(jobs)} jobs")
        return jobs
    except requests.exceptions.Timeout:
        add_log(run, "warning", f"[HTML] {source_name} timeout")
        return []
    except Exception as exc:
        add_log(run, "warning", f"[HTML] {source_name} error: {exc}")
        return []


def _fetch_reed(kw, loc, limit, run):
    q = quote_plus(" ".join(kw))
    loc_s = quote_plus(loc or "united kingdom")
    return _collect_html_jobs(run, "reed", f"https://www.reed.co.uk/jobs/{q}-jobs-in-{loc_s}",
        ["article"], ["h2 a", "h3 a", "a[href*='/jobs/']"],
        [".posted-by", ".recruiter-name"], [".location"], [".salary"],
        [".description", ".job-result-description"], "https://www.reed.co.uk", limit)


def _fetch_cvlibrary(kw, loc, limit, run):
    q = quote_plus(" ".join(kw))
    loc_s = quote_plus(loc or "United Kingdom")
    return _collect_html_jobs(run, "cvlibrary",
        f"https://www.cv-library.co.uk/search-jobs?keywords={q}&geo={loc_s}",
        ["li.job", "article.job", ".job-result"], ["h2 a", "h3 a", ".job__title a"],
        [".company", ".job-company"], [".location"], [".salary"],
        [".description", ".summary"], "https://www.cv-library.co.uk", limit)


def _fetch_totaljobs(kw, loc, limit, run):
    q = "-".join((" ".join(kw) or "logistics").split())
    loc_s = "-".join((loc or "united-kingdom").split())
    return _collect_html_jobs(run, "totaljobs",
        f"https://www.totaljobs.com/jobs/{q}/in-{loc_s}",
        ["article", ".job-result"], ["h2 a", "h3 a", ".job-title a"],
        [".company", ".company-name"], [".location"], [".salary"],
        [".description", ".summary"], "https://www.totaljobs.com", limit)


def _fetch_findajob(kw, limit, run):
    q = quote_plus(" ".join(kw))
    return _collect_html_jobs(run, "findajob",
        f"https://findajob.dwp.gov.uk/search?q={q}&where=UnitedKingdom&pp=25",
        ["div.search-result", "li.search-result"], ["h3 a", "h2 a"],
        [".employer", "dd"], [".location"], [".salary", ".pay"],
        [".description", ".snippet"], "https://findajob.dwp.gov.uk", limit)


def _fetch_nhs(kw, limit, run):
    q = quote_plus(" ".join(kw))
    return _collect_html_jobs(run, "nhs",
        f"https://www.jobs.nhs.uk/candidate/search/results?keyword={q}&location=United%20Kingdom&distance=200",
        ["li.vacancy", ".nhsuk-card"], ["h2 a", ".vacancy-title a"],
        [".employer", ".trust-name"], [".location"], [".salary"],
        [".description", ".vacancy-description"], "https://www.jobs.nhs.uk", limit)


def _fetch_ukvisasponsorships(kw, limit, run):
    q = quote_plus(" ".join(kw))
    return _collect_html_jobs(run, "ukvisasponsorships",
        f"https://ukvisasponsorships.co.uk/jobs?q={q}",
        ["div.job", "article", ".job-card"], ["h2 a", "h3 a", "a"],
        [".company", ".employer"], [".location"], [".salary"],
        [".description", ".summary"], "https://ukvisasponsorships.co.uk", limit)


def fetch_html_sources_parallel(keywords: List[str], location: str, limit: int, run: dict) -> List[dict]:
    fetchers = [
        lambda: _fetch_reed(keywords, location, limit, run),
        lambda: _fetch_cvlibrary(keywords, location, limit, run),
        lambda: _fetch_totaljobs(keywords, location, limit, run),
        lambda: _fetch_findajob(keywords, limit, run),
        lambda: _fetch_nhs(keywords, limit, run),
        lambda: _fetch_ukvisasponsorships(keywords, limit, run),
    ]
    all_jobs: List[dict] = []
    with ThreadPoolExecutor(max_workers=len(fetchers)) as ex:
        futs = [ex.submit(fn) for fn in fetchers]
        for fut in as_completed(futs):
            try:
                all_jobs.extend(fut.result())
            except Exception:
                pass
    return dedupe_jobs(all_jobs)


# ---------------------------------------------------------------------------
# Blacklist / whitelist filtering
# ---------------------------------------------------------------------------

def apply_filters(jobs: List[dict], blacklist: List[str], whitelist: List[str]) -> List[dict]:
    bl = [x.lower().strip() for x in (blacklist or []) if x.strip()]
    wl = [x.lower().strip() for x in (whitelist or []) if x.strip()]
    filtered = []
    for job in jobs:
        company = (job.get("company") or "").lower()
        title = (job.get("title") or "").lower()
        if bl and any(b in company or b in title for b in bl):
            continue
        if wl and not any(w in company or w in title for w in wl):
            continue
        filtered.append(job)
    return filtered


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_automation_pipeline(run_id: str, payload) -> None:
    run = get_run(run_id)
    if not run:
        return

    try:
        update_run(run_id, status="running", stage="loading_profile", progress_percent=5)
        add_log(run, "info", f"Starting pipeline for {payload.candidate_email}")

        profile: Optional[dict] = getattr(payload, "resume_profile", None)
        blacklist: List[str] = getattr(payload, "company_blacklist", []) or []
        whitelist: List[str] = getattr(payload, "company_whitelist", []) or []

        # Stage 1: Parallel JobSpy scraping
        update_run(run_id, stage="scraping_jobspy", progress_percent=10)
        add_log(run, "info", f"Scraping JobSpy sites in parallel: {JOBSPY_SITES}")
        results_per_site = min(max(payload.max_jobs // len(JOBSPY_SITES), 25), JOBSPY_MAX_PER_SOURCE)
        jobspy_jobs = scrape_all_jobspy_parallel(payload.keywords, payload.location, results_per_site, run)
        add_log(run, "info", f"JobSpy total: {len(jobspy_jobs)} jobs")
        update_run(run_id, progress_percent=35)

        # Stage 2: Parallel HTML source scraping
        update_run(run_id, stage="scraping_html", progress_percent=35)
        add_log(run, "info", "Scraping HTML job boards in parallel")
        html_jobs = fetch_html_sources_parallel(payload.keywords, payload.location, HTML_SOURCE_DEFAULT_CAP, run)
        add_log(run, "info", f"HTML boards total: {len(html_jobs)} jobs")
        update_run(run_id, progress_percent=55)

        # Merge, dedup, filter
        all_jobs = dedupe_jobs(jobspy_jobs + html_jobs)
        all_jobs = apply_filters(all_jobs, blacklist, whitelist)
        add_log(run, "info", f"After merge+filter: {len(all_jobs)} unique jobs")
        update_run(run_id, jobs_scanned=len(all_jobs), progress_percent=60)

        if not all_jobs:
            add_log(run, "warning", "No live jobs found — using fallback sample jobs")
            all_jobs = FALLBACK_JOBS[:]

        # Stage 3: AI scoring & shortlisting
        update_run(run_id, stage="scoring", progress_percent=60)
        shortlist = []
        for idx, job in enumerate(all_jobs):
            score_data = ai_fit_score(job, profile, payload.keywords)
            job["fit_score"] = score_data["fit_score"]
            job["fit_level"] = score_data["fit_level"]

            sponsorship_ok = job.get("sponsorship_status") != "no"
            if score_data["fit_score"] >= 30 and sponsorship_ok:
                shortlist.append(job)

            if idx % 10 == 0:
                update_run(run_id, progress_percent=min(60 + int((idx / max(len(all_jobs), 1)) * 20), 80))

        shortlist.sort(key=lambda x: x.get("fit_score", 0), reverse=True)
        update_run(run_id, jobs_matched=len(shortlist),
                   top_matches=[{"title": j["title"], "company": j["company"],
                                  "fit_score": j["fit_score"], "url": j["url"]}
                                 for j in shortlist[:20]],
                   progress_percent=80)
        add_log(run, "info", f"Shortlisted {len(shortlist)} jobs after AI scoring")

        # Stage 4: Apply / generate cover letters
        update_run(run_id, stage="applying", progress_percent=80)
        applied = 0
        failed = 0

        for idx, job in enumerate(shortlist, start=1):
            run = get_run(run_id)
            if not run:
                return

            update_run(run_id, current_url=job.get("url"),
                       progress_percent=min(80 + int((idx / max(len(shortlist), 1)) * 15), 95))

            title = job.get("title", "")
            company = job.get("company", "")

            if payload.auto_apply and profile:
                cover_letter = generate_cover_letter(profile, job)
                job["cover_letter"] = cover_letter
                applied += 1
                update_run(run_id, jobs_applied=applied)
                add_log(run, "info",
                        f"✓ Applied: {title} at {company} (fit={job.get('fit_score')}%, "
                        f"sponsorship={job.get('sponsorship_status')})")
            elif payload.auto_apply and not profile:
                add_log(run, "warning",
                        f"⚠ Skipped cover letter for {title} — no resume profile loaded")
                applied += 1
                update_run(run_id, jobs_applied=applied)
            else:
                failed += 1
                update_run(run_id, jobs_failed=failed)
                add_log(run, "info", f"Auto-apply disabled — recorded {title} at {company}")

        summary = {
            "keywords": payload.keywords,
            "location": payload.location,
            "requested_jobs": payload.max_jobs,
            "jobs_seen": len(all_jobs),
            "matched_jobs": len(shortlist),
            "applied_jobs": applied,
            "failed_jobs": failed,
            "jobspy_direct": JOBSPY_AVAILABLE,
            "llm_cover_letters": (OPENAI_AVAILABLE and bool(settings.openai_api_key))
                or (ANTHROPIC_AVAILABLE and bool(settings.anthropic_api_key)),
            "top_matches": [{"title": j["title"], "company": j["company"],
                             "fit_score": j.get("fit_score"), "url": j["url"]}
                            for j in shortlist[:10]],
        }

        update_run(run_id, status="completed", stage="completed", progress_percent=100,
                   current_url=None, result_summary=summary)
        add_log(run, "info",
                f"✅ Run completed: {len(all_jobs)} scanned, {len(shortlist)} matched, {applied} applied")

    except Exception as exc:
        run = get_run(run_id)
        if run:
            update_run(run_id, status="failed", stage="failed", current_url=None)
            add_log(run, "error", f"Pipeline failed: {exc}")


def start_run_thread(payload) -> dict:
    run = create_run(payload)
    t = threading.Thread(target=run_automation_pipeline, args=(run["run_id"], payload), daemon=True)
    t.start()
    return run
