"""
automation_runtime.py – streaming apply pipeline

Focused on: Logistics & Supply Chain Management roles (UK)

LLM priority (all free first):
  1. Google Gemini 1.5 Flash  — FREE, 1500 req/day
  2. HuggingFace Inference API — FREE tier
  3. Smart offline template   — ZERO API, always works
  4. OpenAI / Anthropic       — optional paid fallback

Job sources:
  JobSpy  : LinkedIn, Indeed, Google  (Glassdoor removed — broken upstream since May 2025)
  HTML    : Reed, CV-Library, TotalJobs, FindAJob, NHS, UKVisaSponsorships,
            CWJobs, Guardian Jobs, Glassdoor (direct HTML)
  API     : Adzuna (free UK job API, keyless fallback supported)

VISA SPONSORSHIP STRATEGY (evidence-based, Jan 2027 deadline):
  Source: Reddit r/SkilledWorkerVisaUK, r/ukvisa, GOV.UK, HirEdge 2026, VisaResume 2026

  VERDICT: ALWAYS disclose visa need. But lead with VALUE, end with sponsorship.

  Why disclose:
    - Employers who cannot sponsor will filter out → saves application time for Jan deadline
    - Employers who CAN sponsor must know upfront to initiate Certificate of Sponsorship (CoS)
      process with UKVI — they cannot do this retroactively after offer
    - Not disclosing = 'bait and switch' — damages trust, wastes interview slots
    - Reddit consensus (r/SkilledWorkerVisaUK 2025-2026): "only apply to licensed sponsors,
      disclose at first interaction"

  How to frame it (NOT apologetic, NOT a request):
    ✅ "I would require a Certificate of Sponsorship and note that [Company] holds a
        Skilled Worker sponsor licence." — factual, confident, shows you've done homework
    ❌ "I need sponsorship" — leads with cost, puts burden on them
    ❌ Not mentioning it — employer finds out later, CoS process too late

  Where to put it: FINAL paragraph of cover letter, LAST line of cold email.
  Exception: if job posting explicitly mentions sponsorship available, reference it early.
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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

try:
    from jobspy import scrape_jobs as _jobspy_scrape
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False

try:
    from groq import Groq as _Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

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
from backend.pipeline import scoring as _scoring
from backend.pipeline import drafting as _drafting
from backend.pipeline.orchestrator import gather_jobs as _gather_jobs

# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------
RUNS: Dict[str, dict] = {}
RUN_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
JOBSPY_SITES          = ["linkedin", "indeed", "google"]
JOBSPY_FALLBACK_URL   = "http://127.0.0.1:8010"
JOBSPY_MAX_PER_SOURCE = 100
HTML_SOURCE_CAP       = 150

# Minimum fit score to include a job in results.
# Lowered to 10 so title-only matches (short LinkedIn descriptions) still surface.
MIN_FIT_SCORE = 10

# ---------------------------------------------------------------------------
# VISA SPONSORSHIP DISCLOSURE
# Evidence-based strategy from Reddit r/SkilledWorkerVisaUK, r/ukvisa, GOV.UK.
# Always disclose — but lead with value, end with sponsorship as logistics.
# ---------------------------------------------------------------------------
SPONSORSHIP_DISCLOSURE_CL = (
    "I would require a Certificate of Sponsorship under the Skilled Worker route. "
    "I have confirmed that {company} holds a sponsor licence and am fully prepared to "
    "support the compliance process — this is straightforward from the candidate side."
)
SPONSORSHIP_DISCLOSURE_CL_UNKNOWN = (
    "I would require a Certificate of Sponsorship under the Skilled Worker route. "
    "I would welcome the chance to discuss whether {company} is able to support this — "
    "I am prepared to make the process as simple as possible."
)
SPONSORSHIP_DISCLOSURE_EMAIL = (
    "Note: I require a Certificate of Sponsorship (Skilled Worker route) — "
    "happy to discuss this on a call."
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# HTTP session with retry + backoff (avoids transient 429 / 503 blocks)
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(REQUEST_HEADERS)
    return session

# ---------------------------------------------------------------------------
# SEARCH TRACKS  —  Logistics & Supply Chain ONLY
# ---------------------------------------------------------------------------
SUPPLY_CHAIN_KEYWORDS = [
    "supply chain analyst",
    "logistics coordinator",
    "procurement analyst",
    "demand planner",
    "inventory analyst",
    "operations analyst",
    "supply chain coordinator",
    "logistics analyst",
    "supply chain graduate",
    "graduate logistics",
    "warehouse operations",
    "transport planner",
    "import export coordinator",
    "purchasing analyst",
    "s&op analyst",
    "materials planner",
    "stock controller",
    "freight coordinator",
    "distribution analyst",
]

SUPPLY_CHAIN_BROAD = [
    "supply chain",
    "logistics",
    "procurement",
    "operations",
    "warehouse",
    "freight",
]

FALLBACK_JOBS = [
    {
        "title": "Supply Chain Analyst", "company": "DHL",
        "location": "United Kingdom",
        "url": "https://www.dhl.com/gb-en/home/careers.html",
        "sponsorship_status": "yes",
        "description": "Supply chain analyst, transport planning, forecasting, Excel, SAP, logistics.",
        "source": "fallback", "recruiter_email": None,
    },
    {
        "title": "Graduate Logistics Coordinator", "company": "Amazon",
        "location": "United Kingdom",
        "url": "https://www.amazon.jobs",
        "sponsorship_status": "unknown",
        "description": "Graduate logistics, supply chain operations, Excel, analytical skills, coordinator.",
        "source": "fallback", "recruiter_email": None,
    },
    {
        "title": "Procurement Analyst", "company": "NHS Supply Chain",
        "location": "United Kingdom",
        "url": "https://www.jobs.nhs.uk",
        "sponsorship_status": "yes",
        "description": "Procurement analyst, supply chain, vendor management, SAP, Excel, operations.",
        "source": "fallback", "recruiter_email": None,
    },
    {
        "title": "Demand Planning Analyst", "company": "Unilever",
        "location": "United Kingdom",
        "url": "https://careers.unilever.com",
        "sponsorship_status": "yes",
        "description": "Demand planning, S&OP, forecasting, supply chain, Excel, SAP, analytics.",
        "source": "fallback", "recruiter_email": None,
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def add_log(run: dict, level: str, message: str) -> None:
    run["logs"].append({"ts": now_iso(), "level": level, "message": message})
    run["logs"] = run["logs"][-3000:]

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
        "run_id":            run_id,
        "candidate_email":   payload.candidate_email,
        "status":            "queued",
        "stage":             "queued",
        "progress_percent":  0,
        "jobs_scanned":      0,
        "jobs_matched":      0,
        "jobs_applied":      0,
        "jobs_failed":       0,
        "current_url":       None,
        "logs":              [],
        "result_summary":    None,
        "top_matches":       [],
        "applied_jobs":      [],
        "created_at":        now_iso(),
        "used_mock":         False,
        "source_used":       None,
    }
    add_log(run, "info", "Run created.")
    with RUN_LOCK:
        RUNS[run_id] = run
    return run

# ---------------------------------------------------------------------------
# Sponsorship classifier
# ---------------------------------------------------------------------------

def classify_sponsorship(description: str) -> str:
    # Canonical implementation now lives in backend.pipeline.scoring; kept here
    # as a thin delegate so existing imports/tests keep working.
    return _scoring.classify_sponsorship(description)


# Lazily-built, cached GOV.UK sponsor register. Building it may hit the network,
# so we do it once on first use and degrade gracefully to no verifier (jobs then
# fall back to the weaker "mentioned"/"unknown" tiers) if it is unavailable.
_SPONSOR_REGISTER = None
_SPONSOR_REGISTER_TRIED = False


def _sponsor_verifier():
    global _SPONSOR_REGISTER, _SPONSOR_REGISTER_TRIED
    if not _SPONSOR_REGISTER_TRIED:
        _SPONSOR_REGISTER_TRIED = True
        try:
            from backend.services.sponsor_register import SponsorRegister
            _SPONSOR_REGISTER = SponsorRegister()
        except Exception:
            _SPONSOR_REGISTER = None
    return _SPONSOR_REGISTER.verify if _SPONSOR_REGISTER else None


def sponsor_tier(job: dict) -> str:
    """Authoritative sponsorship tier for a job (see scoring.sponsorship_tier)."""
    return _scoring.sponsorship_tier(job, _sponsor_verifier())

# ---------------------------------------------------------------------------
# Fit scoring
# ---------------------------------------------------------------------------

def ai_fit_score(job: dict, profile: Optional[dict], keywords: List[str]) -> dict:
    # Canonical scorer now lives in backend.pipeline.scoring; kept here as a thin
    # delegate so existing imports/tests keep working.
    return _scoring.score_job(job, profile, keywords)

# ---------------------------------------------------------------------------
# LLM — FREE first, paid optional, offline always works
# ---------------------------------------------------------------------------

_GROQ_MODEL = "llama-3.3-70b-versatile"
_groq_client = None


def _groq(prompt: str, max_tokens: int = 500) -> Optional[str]:
    """Primary LLM — Groq free tier. Returns None if unavailable so the
    chain can fall through to the next provider / offline template."""
    global _groq_client
    key = getattr(settings, "groq_api_key", None)
    if not GROQ_AVAILABLE or not key:
        return None
    try:
        if _groq_client is None:
            _groq_client = _Groq(api_key=key)
        resp = _groq_client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception:
        return None


def _gemini(prompt: str, max_tokens: int = 500) -> Optional[str]:
    key = getattr(settings, "gemini_api_key", None)
    if not key:
        return None
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={key}"
        )
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.75},
        }
        resp = requests.post(url, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None

def _huggingface(prompt: str, max_tokens: int = 500) -> Optional[str]:
    key = getattr(settings, "hf_api_key", None)
    if not key:
        return None
    try:
        url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"inputs": prompt,
                  "parameters": {"max_new_tokens": max_tokens, "temperature": 0.75,
                                 "return_full_text": False}},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0].get("generated_text", "").strip()
        return None
    except Exception:
        return None

def _openai_llm(prompt: str, max_tokens: int = 500) -> Optional[str]:
    if not OPENAI_AVAILABLE or not getattr(settings, "openai_api_key", None):
        return None
    try:
        client = _openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens, temperature=0.75,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None

def _anthropic_llm(prompt: str, max_tokens: int = 500) -> Optional[str]:
    if not ANTHROPIC_AVAILABLE or not getattr(settings, "anthropic_api_key", None):
        return None
    try:
        client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model="claude-3-haiku-20240307", max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return None

def _llm(prompt: str, max_tokens: int = 500) -> Optional[str]:
    # Priority: Groq (free primary) → Gemini → HuggingFace → OpenAI → Anthropic.
    # All return None when their key/package is missing, so the caller falls
    # back to the offline template and the pipeline always produces output.
    return (
        _groq(prompt, max_tokens)
        or _gemini(prompt, max_tokens)
        or _huggingface(prompt, max_tokens)
        or _openai_llm(prompt, max_tokens)
        or _anthropic_llm(prompt, max_tokens)
    )

# ---------------------------------------------------------------------------
# LLM generation (public)
# ---------------------------------------------------------------------------

def generate_cover_letter(profile: dict, job: dict) -> str:
    # Canonical drafting lives in backend.pipeline.drafting; the local _llm chain
    # (Groq -> Gemini -> HF -> OpenAI -> Anthropic -> offline) is injected so the
    # provider fallback behaviour is unchanged.
    return _drafting.draft_cover_letter(profile, job, llm_fn=_llm)

def generate_cold_email(profile: dict, job: dict) -> str:
    return _drafting.draft_cold_email(profile, job, llm_fn=_llm)

def generate_resume_tailoring(profile: dict, job: dict) -> dict:
    try:
        from backend.services.resume.resume_tailor_service import tailor_resume
        return tailor_resume({"profile": profile, "job": job})
    except Exception:
        return {"note": "Resume tailoring unavailable"}

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
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique

# ---------------------------------------------------------------------------
# JobSpy scraping
# ---------------------------------------------------------------------------

def _safe_val(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value

def jobspy_scrape_site(site: str, keywords: List[str], location: str, run: dict) -> List[dict]:
    search_term = " ".join(keywords[:3]).strip() or "supply chain logistics"
    add_log(run, "info", f"[JobSpy] {site} → '{search_term}'")
    try:
        df = _jobspy_scrape(
            site_name=[site],
            search_term=search_term,
            location=location or "United Kingdom",
            results_wanted=JOBSPY_MAX_PER_SOURCE,
            country_indeed="UK",
            linkedin_fetch_description=True,
        )
        rows = []
        for _, row in df.iterrows():
            desc = _safe_val(row.get("description")) or ""
            rows.append({
                "title":              _safe_val(row.get("title")) or "Unknown title",
                "company":            _safe_val(row.get("company")) or "Unknown company",
                "location":           _safe_val(row.get("location")) or location,
                "salary":             str(_safe_val(row.get("min_amount")) or ""),
                "url":                _safe_val(row.get("job_url")) or "",
                "sponsorship_status": classify_sponsorship(desc),
                "description":        desc,
                "source":             site,
                "date_posted":        str(_safe_val(row.get("date_posted")) or ""),
                "recruiter_email":    _safe_val(row.get("emails")),
            })
        add_log(run, "info", f"[JobSpy] {site} → {len(rows)} jobs")
        return rows
    except Exception as exc:
        add_log(run, "warning", f"[JobSpy] {site} skipped: {exc}")
        return []

def jobspy_fallback_http(site: str, keywords: List[str], location: str, run: dict) -> List[dict]:
    search_term = " ".join(keywords[:3]).strip() or "supply chain logistics"
    params = {
        "site_name": site, "search_term": search_term,
        "location": location or "United Kingdom",
        "results_wanted": JOBSPY_MAX_PER_SOURCE, "offset": 0,
    }
    try:
        resp = requests.get(f"{JOBSPY_FALLBACK_URL}/search_jobs", params=params, timeout=(5, 120))
        if resp.status_code != 200:
            return []
        rows = []
        for row in resp.json().get("results", []):
            desc = row.get("description") or ""
            rows.append({
                "title":              row.get("title") or "Unknown title",
                "company":            row.get("company") or "Unknown company",
                "location":           row.get("location") or location,
                "salary":             str(row.get("min_amount") or ""),
                "url":                row.get("job_url") or "",
                "sponsorship_status": classify_sponsorship(desc),
                "description":        desc,
                "source":             site,
                "recruiter_email":    None,
            })
        return rows
    except Exception as exc:
        add_log(run, "warning", f"[JobSpy-HTTP] {site} skipped: {exc}")
        return []

def scrape_all_jobspy(keywords: List[str], location: str, run: dict) -> List[dict]:
    fn = jobspy_scrape_site if JOBSPY_AVAILABLE else jobspy_fallback_http
    all_jobs: List[dict] = []
    kw_sets = [
        keywords,
        SUPPLY_CHAIN_KEYWORDS[:5],
        SUPPLY_CHAIN_KEYWORDS[5:10],
        SUPPLY_CHAIN_BROAD[:3],
    ]
    tasks = [(site, kws) for kws in kw_sets for site in JOBSPY_SITES]
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(fn, site, kws, location, run): site for site, kws in tasks}
        for fut in as_completed(futures):
            try:
                all_jobs.extend(fut.result())
            except Exception as exc:
                add_log(run, "warning", f"[JobSpy] thread error: {exc}")
    deduped = dedupe_jobs(all_jobs)
    add_log(run, "info", f"[JobSpy] total deduped: {len(deduped)}")
    return deduped

# ---------------------------------------------------------------------------
# Adzuna API scraper
# ---------------------------------------------------------------------------

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/gb/search"

def _adzuna(keywords: List[str], run: dict) -> List[dict]:
    jobs = []
    search_term = " ".join(keywords[:3]).strip() or "supply chain logistics"
    app_id  = getattr(settings, "adzuna_app_id",  None) or ""
    app_key = getattr(settings, "adzuna_app_key", None) or ""
    add_log(run, "info", f"[Adzuna] '{search_term}' (auth={'yes' if app_id else 'no'})")
    session = _make_session()
    for page in range(1, 4):
        try:
            params: dict = {
                "results_per_page": 50,
                "what": search_term,
                "where": "UK",
                "content-type": "application/json",
            }
            if app_id and app_key:
                params["app_id"]  = app_id
                params["app_key"] = app_key
            resp = session.get(f"{ADZUNA_BASE}/{page}", params=params, timeout=(5, 25))
            if resp.status_code == 401:
                add_log(run, "warning", "[Adzuna] 401 — API keys invalid or missing; skipping")
                break
            if resp.status_code != 200:
                add_log(run, "warning", f"[Adzuna] page {page} returned {resp.status_code}")
                break
            results = resp.json().get("results", [])
            if not results:
                break
            for item in results:
                desc = item.get("description") or ""
                jobs.append({
                    "title":              item.get("title") or "Unknown title",
                    "company":            (item.get("company") or {}).get("display_name") or "Unknown",
                    "location":           (item.get("location") or {}).get("display_name") or "United Kingdom",
                    "salary":             str(item.get("salary_min") or ""),
                    "url":                item.get("redirect_url") or "",
                    "sponsorship_status": classify_sponsorship(desc),
                    "description":        desc,
                    "source":             "adzuna",
                    "recruiter_email":    None,
                })
        except Exception as exc:
            add_log(run, "warning", f"[Adzuna] page {page} error: {exc}")
            break
    add_log(run, "info", f"[Adzuna] → {len(jobs)} jobs")
    return jobs

# ---------------------------------------------------------------------------
# HTML board scraping
# ---------------------------------------------------------------------------

def _html_jobs(run, name, url, card_sels, title_sels, co_sels, loc_sels,
               sal_sels, desc_sels, base, limit):
    jobs = []
    try:
        add_log(run, "info", f"[HTML] {name} → {url[:80]}")
        session = _make_session()
        resp = session.get(url, timeout=(8, 25))
        if resp.status_code != 200:
            add_log(run, "warning", f"[HTML] {name} returned HTTP {resp.status_code}")
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = []
        for s in card_sels:
            cards = soup.select(s)
            if cards:
                break
        if not cards:
            add_log(run, "warning", f"[HTML] {name}: no cards matched selectors {card_sels}")
            return []
        seen = set()
        for card in cards:
            title_text = href = ""
            for s in title_sels:
                el = card.select_one(s)
                if el:
                    title_text = el.get_text(" ", strip=True)
                    href = el.get("href", "")
                    break
            if not title_text or not href:
                continue
            job_url = href if href.startswith("http") else f"{base}{href}"
            if job_url in seen:
                continue
            seen.add(job_url)
            def _t(sels, _card=card):
                for s in sels:
                    el = _card.select_one(s)
                    if el:
                        return el.get_text(" ", strip=True)
                return ""
            desc = _t(desc_sels) or card.get_text(" ", strip=True)[:300]
            jobs.append({
                "title":              title_text,
                "company":            _t(co_sels) or "Unknown",
                "location":           _t(loc_sels) or "United Kingdom",
                "salary":             _t(sal_sels),
                "url":                job_url,
                "sponsorship_status": classify_sponsorship(desc),
                "description":        desc,
                "source":             name,
                "recruiter_email":    None,
            })
            if len(jobs) >= limit:
                break
        add_log(run, "info", f"[HTML] {name} → {len(jobs)} jobs")
    except Exception as exc:
        add_log(run, "warning", f"[HTML] {name} error: {exc}")
    return jobs

def _reed(kw, loc, run):
    q = quote_plus(" ".join(kw[:3]))
    l = quote_plus(loc or "united kingdom")
    return _html_jobs(
        run, "reed",
        f"https://www.reed.co.uk/jobs/{q}-jobs-in-{l}?pageno=1",
        ["article.job-result", "article"],
        ["h3.title a", "h2 a", "a.job-result-heading__title"],
        ["a.gtmJobListingPostedBy", "span.posted-by", ".recruiter"],
        ["li.location span", ".job-result-heading__metadata li"],
        ["li.salary span", ".salary"],
        [".job-result-description__details", ".description"],
        "https://www.reed.co.uk", HTML_SOURCE_CAP)

def _cvlibrary(kw, loc, run):
    q = quote_plus(" ".join(kw[:3]))
    l = quote_plus(loc or "United Kingdom")
    return _html_jobs(
        run, "cvlibrary",
        f"https://www.cv-library.co.uk/search-jobs?keywords={q}&geo={l}&distance=50&action=search",
        ["li.job", "article.job", ".job-item"],
        ["a.job-title", "h2 a", "h3 a"],
        [".company", ".employer-name"],
        [".location", ".job-location"],
        [".salary", ".job-salary"],
        [".description", ".job-description"],
        "https://www.cv-library.co.uk", HTML_SOURCE_CAP)

def _totaljobs(kw, loc, run):
    q = quote_plus(" ".join(kw[:2]) or "logistics")
    l = quote_plus(loc or "United Kingdom")
    return _html_jobs(
        run, "totaljobs",
        f"https://www.totaljobs.com/jobs?keywords={q}&location={l}&radius=50",
        ["article.job-result", "article", ".job-result"],
        ["h2 a", "a.job-result-heading__title", "h3 a"],
        [".job-result-heading__employer", ".company"],
        [".job-result-heading__metadata .location", ".location"],
        [".job-result-heading__metadata .salary", ".salary"],
        [".job-result-description", ".description"],
        "https://www.totaljobs.com", HTML_SOURCE_CAP)

def _cwjobs(kw, loc, run):
    q = quote_plus(" ".join(kw[:3]))
    l = quote_plus(loc or "United Kingdom")
    return _html_jobs(
        run, "cwjobs",
        f"https://www.cwjobs.co.uk/jobs?keywords={q}&location={l}&radius=50",
        ["article.job-result", "article", ".job-result"],
        ["h2 a", "a.job-result-heading__title", "h3 a"],
        [".job-result-heading__employer", ".company", ".employer"],
        [".location"],
        [".salary"],
        [".job-result-description", ".description"],
        "https://www.cwjobs.co.uk", HTML_SOURCE_CAP)

def _guardian(kw, run):
    q = quote_plus(" ".join(kw[:3]))
    return _html_jobs(
        run, "guardian",
        f"https://jobs.theguardian.com/jobs/{q}/",
        [".job-posting", "article", "li.job"],
        ["h2 a", "h3 a", ".job-title a"],
        [".company", ".employer"],
        [".location"],
        [".salary"],
        [".description"],
        "https://jobs.theguardian.com", HTML_SOURCE_CAP)

def _glassdoor_html(kw, run):
    q = quote_plus(" ".join(kw[:3]))
    return _html_jobs(
        run, "glassdoor_html",
        f"https://www.glassdoor.co.uk/Job/united-kingdom-{q}-jobs-SRCH_IL.0,14_IN2_KO15,{15+len(q)}.htm",
        ["li.react-job-listing", "li[data-brandviews]", "article"],
        ["a.jobLink", "a[data-test='job-link']", "h2 a"],
        [".employerName", "[data-test='employer-name']"],
        [".loc", "[data-test='job-location']"],
        [".salary-estimate"],
        [".jobDescriptionContent", ".desc"],
        "https://www.glassdoor.co.uk", HTML_SOURCE_CAP)

def _findajob(kw, run):
    q = quote_plus(" ".join(kw[:2]))
    return _html_jobs(
        run, "findajob",
        f"https://findajob.dwp.gov.uk/search?q={q}&where=United+Kingdom&pp=25",
        ["div.search-result", "li.search-result"],
        ["h3 a", "h2 a"],
        [".employer"],
        [".location"],
        [".salary"],
        [".description"],
        "https://findajob.dwp.gov.uk", HTML_SOURCE_CAP)

def _nhs(kw, run):
    q = quote_plus(" ".join(kw[:2]))
    return _html_jobs(
        run, "nhs",
        f"https://www.jobs.nhs.uk/candidate/search/results?keyword={q}&location=United%20Kingdom&distance=200",
        ["li.vacancy", ".nhsuk-card"],
        ["h2 a", ".vacancy-title a"],
        [".employer"],
        [".location"],
        [".salary"],
        [".description"],
        "https://www.jobs.nhs.uk", HTML_SOURCE_CAP)

def _ukvisasponsorships(kw, run):
    q = quote_plus(" ".join(kw[:2]))
    return _html_jobs(
        run, "ukvisasponsorships",
        f"https://ukvisasponsorships.co.uk/jobs?q={q}",
        ["div.job", "article", ".job-card"],
        ["h2 a", "h3 a"],
        [".company"],
        [".location"],
        [".salary"],
        [".description"],
        "https://ukvisasponsorships.co.uk", HTML_SOURCE_CAP)

def scrape_all_html(keywords: List[str], location: str, run: dict) -> List[dict]:
    sc_kw    = keywords + SUPPLY_CHAIN_KEYWORDS[:4]
    broad_kw = SUPPLY_CHAIN_BROAD[:3]
    visa_kw  = ["visa sponsorship supply chain", "skilled worker logistics", "sponsorship procurement"]

    fetchers = [
        lambda: _reed(sc_kw,    location, run),
        lambda: _reed(broad_kw, location, run),
        lambda: _cvlibrary(sc_kw, location, run),
        lambda: _totaljobs(sc_kw,    location, run),
        lambda: _totaljobs(broad_kw, location, run),
        lambda: _cwjobs(sc_kw,    location, run),
        lambda: _cwjobs(broad_kw, location, run),
        lambda: _guardian(sc_kw, run),
        lambda: _glassdoor_html(sc_kw,    run),
        lambda: _glassdoor_html(broad_kw, run),
        lambda: _findajob(sc_kw, run),
        lambda: _nhs(sc_kw, run),
        lambda: _ukvisasponsorships(sc_kw,  run),
        lambda: _ukvisasponsorships(visa_kw, run),
        lambda: _adzuna(sc_kw,    run),
        lambda: _adzuna(broad_kw, run),
        lambda: _adzuna(visa_kw,  run),
    ]

    all_jobs: List[dict] = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for fut in as_completed([ex.submit(fn) for fn in fetchers]):
            try:
                all_jobs.extend(fut.result())
            except Exception as exc:
                add_log(run, "warning", f"[HTML] thread error: {exc}")
    deduped = dedupe_jobs(all_jobs)
    add_log(run, "info", f"[HTML/API] total deduped: {len(deduped)}")
    return deduped

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def apply_filters(jobs, blacklist, whitelist, sponsorship_required: bool = False):
    bl = [x.lower().strip() for x in (blacklist or []) if x.strip()]
    wl = [x.lower().strip() for x in (whitelist or []) if x.strip()]
    out = []
    for job in jobs:
        co = (job.get("company") or "").lower()
        ti = (job.get("title") or "").lower()
        if bl and any(b in co or b in ti for b in bl):
            continue
        if wl and not any(w in co or w in ti for w in wl):
            continue
        if sponsorship_required and job.get("sponsorship_status") == "no":
            continue
        out.append(job)
    return out

# ---------------------------------------------------------------------------
# Stream apply
# ---------------------------------------------------------------------------

def stream_apply_job(job: dict, profile: Optional[dict], keywords: List[str],
                     auto_apply: bool, run: dict, run_id: str) -> None:
    title   = job.get("title", "?")
    company = job.get("company", "?")
    fit     = job.get("fit_score", 0)
    entry = {
        "title":              title,
        "company":            company,
        "url":                job.get("url", ""),
        "fit_score":          fit,
        "sponsorship_status": job.get("sponsorship_status", "unknown"),
        "sponsor_tier":       job.get("sponsor_tier") or sponsor_tier(job),
        "source":             job.get("source", ""),
        "cover_letter":       None,
        "cold_email":         None,
        "resume_guidance":    None,
    }
    if auto_apply and profile:
        try:
            entry["resume_guidance"] = generate_resume_tailoring(
                profile, {"title": title, "company": company,
                          "description": job.get("description", ""),
                          "skills": [], "url": job.get("url", "")})
        except Exception:
            pass
        try:
            entry["cover_letter"] = generate_cover_letter(profile, job)
        except Exception as exc:
            add_log(run, "warning", f"Cover letter failed for {title}: {exc}")
        try:
            entry["cold_email"] = generate_cold_email(profile, job)
        except Exception as exc:
            add_log(run, "warning", f"Cold email failed for {title}: {exc}")
        add_log(run, "info",
                f"✅ {title} @ {company} | fit={fit}% | spons={job.get('sponsorship_status')} | "
                f"cl={'yes' if entry['cover_letter'] else 'no'}")
    else:
        add_log(run, "info", f"📌 {title} @ {company} | fit={fit}%")

    with RUN_LOCK:
        run_obj = RUNS.get(run_id)
        if run_obj:
            run_obj["applied_jobs"].append(entry)
            run_obj["jobs_applied"] = len(run_obj["applied_jobs"])
            run_obj["top_matches"] = sorted(
                run_obj["applied_jobs"],
                key=lambda x: x.get("fit_score", 0), reverse=True,
            )[:20]

# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_automation_pipeline(run_id: str, payload) -> None:
    run = get_run(run_id)
    if not run:
        return
    try:
        update_run(run_id, status="running", stage="scraping", progress_percent=5)
        add_log(run, "info",
                f"Pipeline start | keywords={payload.keywords} | location={payload.location}")
        profile        = getattr(payload, "resume_profile", None)
        blacklist      = getattr(payload, "company_blacklist", []) or []
        whitelist      = getattr(payload, "company_whitelist", []) or []
        auto_apply     = getattr(payload, "auto_apply", True)
        spons_required = getattr(payload, "sponsorship_required", False)

        allow_scraper = getattr(payload, "allow_scraper_fallback", False)
        update_run(run_id,
                   stage="📡 Searching Adzuna (primary) and Reed (secondary) for UK jobs...",
                   progress_percent=5)

        def _search_log(level, msg):
            add_log(run, level, msg)

        gathered = _gather_jobs(
            payload.keywords, payload.location,
            allow_scraper_fallback=allow_scraper, log_fn=_search_log,
        )
        all_jobs = gathered["jobs"]
        for note in gathered["notes"]:
            add_log(run, "info", note)
        # Persist the source/mock status so the UI can show an honest, hard-to-miss
        # banner when the results are not live job data.
        update_run(run_id,
                   used_mock=bool(gathered["used_mock"]),
                   source_used=gathered["source_used"])
        add_log(run, "info",
                f"Source used: {gathered['source_used']} "
                f"({'MOCK — set ADZUNA_APP_ID/ADZUNA_APP_KEY for real data' if gathered['used_mock'] else 'live'})")

        all_jobs = apply_filters(all_jobs, blacklist, whitelist, spons_required)
        update_run(run_id, jobs_scanned=len(all_jobs), progress_percent=50)
        add_log(run, "info", f"Total after filter: {len(all_jobs)}")

        if not all_jobs:
            add_log(run, "warning", "No jobs after filtering — showing sample jobs")
            all_jobs = FALLBACK_JOBS[:]
            # These are built-in sample jobs, not live data — flag it honestly.
            update_run(run_id, jobs_scanned=len(all_jobs),
                       used_mock=True, source_used="mock")

        update_run(run_id,
                   stage="🤖 Scoring jobs and generating cover letters...",
                   progress_percent=50)
        matched = 0
        for idx, job in enumerate(all_jobs):
            score_data = ai_fit_score(job, profile, payload.keywords)
            job["fit_score"] = score_data["fit_score"]
            job["fit_level"] = score_data["fit_level"]

            if score_data["fit_score"] >= MIN_FIT_SCORE and job.get("sponsorship_status") != "no":
                matched += 1
                update_run(run_id, jobs_matched=matched)
                stream_apply_job(job, profile, payload.keywords, auto_apply, run, run_id)

            if idx % 10 == 0:
                pct = 50 + int((idx / max(len(all_jobs), 1)) * 45)
                update_run(run_id, progress_percent=min(pct, 95),
                           current_url=job.get("url"),
                           stage=f"🤖 Processing {idx+1}/{len(all_jobs)} jobs...")

        final_run = get_run(run_id) or {}
        summary = {
            "keywords":     payload.keywords,
            "location":     payload.location,
            "jobs_seen":    len(all_jobs),
            "matched_jobs": matched,
            "used_mock":    bool(final_run.get("used_mock")),
            "source_used":  final_run.get("source_used"),
            "applied_jobs": len(final_run.get("applied_jobs", [])),
            "top_matches": [
                {"title": j["title"], "company": j["company"],
                 "fit_score": j.get("fit_score"), "url": j["url"]}
                for j in sorted(final_run.get("applied_jobs", []),
                                key=lambda x: x.get("fit_score", 0), reverse=True)[:10]
            ],
        }
        update_run(run_id, status="completed", stage="✅ Done!",
                   progress_percent=100, current_url=None, result_summary=summary)
        add_log(run, "info",
                f"✅ Done: {len(all_jobs)} scanned, {matched} matched, "
                f"{summary['applied_jobs']} applications prepared")
    except Exception as exc:
        run = get_run(run_id)
        if run:
            update_run(run_id, status="failed", stage="failed", current_url=None)
            add_log(run, "error", f"Pipeline crashed: {exc}")

def start_run_thread(payload) -> dict:
    run = create_run(payload)
    threading.Thread(
        target=run_automation_pipeline, args=(run["run_id"], payload), daemon=True,
    ).start()
    return run
