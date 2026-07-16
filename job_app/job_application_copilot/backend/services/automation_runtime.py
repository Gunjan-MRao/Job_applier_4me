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
  API     : Adzuna (free, 100 results/call, full descriptions)
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
# Glassdoor removed from JobSpy — broken upstream (400/403) since May 2025.
# We scrape Glassdoor directly via _glassdoor_html() instead.
JOBSPY_SITES          = ["linkedin", "indeed", "google"]
JOBSPY_FALLBACK_URL   = "http://127.0.0.1:8010"
JOBSPY_MAX_PER_SOURCE = 100   # raised from 50
HTML_SOURCE_CAP       = 150   # raised from 100

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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
    }
    add_log(run, "info", "Run created.")
    with RUN_LOCK:
        RUNS[run_id] = run
    return run

# ---------------------------------------------------------------------------
# Sponsorship classifier
# ---------------------------------------------------------------------------

def classify_sponsorship(description: str) -> str:
    text = (description or "").lower()
    negative = [
        "no sponsorship", "unable to sponsor", "must have right to work",
        "no visa sponsorship", "cannot sponsor", "not able to sponsor",
        "without sponsorship", "you must already have the right to work",
        "must already hold", "no tier 2", "must be eligible to work in the uk",
        "no work permit", "will not sponsor",
    ]
    positive = [
        "visa sponsorship", "sponsorship available", "skilled worker visa",
        "certificate of sponsorship", "cos available", "we can sponsor",
        "eligible for sponsorship", "sponsorship may be available",
        "tier 2", "skilled worker", "sponsor a visa",
    ]
    if any(x in text for x in negative):
        return "no"
    if any(x in text for x in positive):
        return "yes"
    return "unknown"

# ---------------------------------------------------------------------------
# Fit scoring
# ---------------------------------------------------------------------------

ENTRY_LEVEL_TITLES = [
    "graduate", "junior", "entry level", "entry-level", "trainee",
    "assistant", "associate", "coordinator", "analyst", "apprentice",
]

SC_CORE_TERMS = [
    "supply chain", "logistics", "procurement", "operations",
    "warehouse", "transport", "inventory", "demand plan", "forecasting",
    "s&op", "purchasing", "vendor", "freight", "distribution",
    "sap", "erp", "excel",
]

def ai_fit_score(job: dict, profile: Optional[dict], keywords: List[str]) -> dict:
    title    = (job.get("title") or "").lower()
    desc     = (job.get("description") or "").lower()
    combined = f"{title} {desc}"

    kw_hits     = sum(1 for kw in keywords if kw and kw.strip().lower() in combined)
    kw_score    = min(int(kw_hits / max(len(keywords), 1) * 60), 60)
    sc_hits     = sum(1 for t in SC_CORE_TERMS if t in combined)
    sc_bonus    = min(sc_hits * 3, 20)
    entry_bonus = 15 if any(t in title for t in ENTRY_LEVEL_TITLES) else 0
    spons_bonus = 10 if job.get("sponsorship_status") == "yes" else 0

    senior_terms   = ["senior", "lead", "head of", "director", "principal", "vp ", "manager"]
    exp_hint       = (profile or {}).get("years_of_experience_hint") or ""
    has_experience = any(c.isdigit() for c in exp_hint)
    senior_penalty = -20 if any(t in title for t in senior_terms) and not has_experience else 0

    score = max(0, min(kw_score + sc_bonus + entry_bonus + spons_bonus + senior_penalty, 100))
    level = "strong" if score >= 60 else ("moderate" if score >= 30 else "weak")
    return {"fit_score": score, "fit_level": level, "reasons": [], "gaps": []}

# ---------------------------------------------------------------------------
# LLM — FREE first, paid optional, offline always works
# ---------------------------------------------------------------------------

def _gemini(prompt: str, max_tokens: int = 500) -> Optional[str]:
    key = settings.gemini_api_key
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
    key = settings.hf_api_key
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
    if not OPENAI_AVAILABLE or not settings.openai_api_key:
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
    if not ANTHROPIC_AVAILABLE or not settings.anthropic_api_key:
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
    return (
        _gemini(prompt, max_tokens)
        or _huggingface(prompt, max_tokens)
        or _openai_llm(prompt, max_tokens)
        or _anthropic_llm(prompt, max_tokens)
    )

# ---------------------------------------------------------------------------
# Offline cover letter + cold email
# ---------------------------------------------------------------------------

def _offline_cover_letter(profile: dict, job: dict) -> str:
    name      = profile.get("candidate_name") or "Applicant"
    title     = job.get("title", "the role")
    company   = job.get("company", "your company")
    skills    = profile.get("skills") or []
    exp       = profile.get("years_of_experience_hint") or "relevant"
    roles     = profile.get("likely_roles") or []
    sc_skills = [s for s in skills if s in (
        "supply chain", "logistics", "procurement", "sap", "excel",
        "forecasting", "demand planning", "inventory management",
        "operations", "erp", "power bi", "sql",
    )]
    top_skills = ", ".join(sc_skills[:3]) if sc_skills else ", ".join(skills[:3]) or "my skills"
    role_bg    = roles[0].title() if roles else "supply chain and logistics"
    desc = (job.get("description") or "").lower()
    if "sap" in desc:
        detail = "I have hands-on experience with SAP which I understand is central to this role."
    elif "excel" in desc or "spreadsheet" in desc:
        detail = "I am proficient in Excel and comfortable building models and dashboards from scratch."
    elif "forecasting" in desc or "demand" in desc:
        detail = "I have worked on demand forecasting and inventory optimisation, and I am confident I can contribute quickly."
    else:
        detail = "I am confident my background in supply chain and logistics aligns well with what you are looking for."
    return (
        f"Dear Hiring Team at {company},\n\n"
        f"I am writing to express my strong interest in the {title} position at {company}.\n\n"
        f"My background in {role_bg} has equipped me with {exp} of experience working with "
        f"{top_skills}. {detail}\n\n"
        f"I am actively seeking a role in the UK where I can grow and make a tangible impact. "
        f"I would welcome the chance to discuss how I can contribute — "
        f"would you be open to a brief call this week?\n\n"
        f"Thank you for your consideration.\n\nKind regards,\n{name}"
    )

def _offline_cold_email(profile: dict, job: dict) -> str:
    name      = profile.get("candidate_name") or "Applicant"
    title     = job.get("title", "the role")
    company   = job.get("company", "your company")
    skills    = profile.get("skills") or []
    exp       = profile.get("years_of_experience_hint") or "relevant"
    sc_skills = [s for s in skills if s in (
        "supply chain", "logistics", "procurement", "sap", "excel", "operations",
    )]
    top_skills = ", ".join(sc_skills[:3]) if sc_skills else ", ".join(skills[:2]) or "supply chain"
    return (
        f"Subject: {title} — {name}\n\n"
        f"Hi,\n\n"
        f"I came across the {title} role at {company} and wanted to reach out directly.\n\n"
        f"I have {exp} experience in {top_skills} and am actively looking for a "
        f"supply chain or logistics role in the UK. "
        f"I am a quick learner, detail-oriented, and ready to contribute from day one.\n\n"
        f"Would you have 15 minutes for a quick chat?\n\nBest,\n{name}"
    )

# ---------------------------------------------------------------------------
# LLM generation (public)
# ---------------------------------------------------------------------------

def generate_cover_letter(profile: dict, job: dict) -> str:
    name      = profile.get("candidate_name") or "Applicant"
    title     = job.get("title", "the role")
    company   = job.get("company", "your company")
    sc_skills = [s for s in (profile.get("skills") or []) if s in (
        "supply chain", "logistics", "procurement", "sap", "excel",
        "forecasting", "demand planning", "inventory management",
        "operations", "erp", "power bi", "sql", "s&op",
    )]
    skills_str = ", ".join(sc_skills[:6]) or ", ".join((profile.get("skills") or [])[:6])
    exp        = profile.get("years_of_experience_hint") or "some"
    desc_snip  = (job.get("description") or "")[:400]
    prompt = (
        f"Write a concise, genuine cover letter for {name} applying for '{title}' at {company}. "
        f"The candidate has {exp} experience in supply chain and logistics with skills: {skills_str}. "
        f"Job excerpt: {desc_snip}. "
        "Rules: under 220 words, warm human tone, no filler openers like 'I am writing to', "
        "no square brackets, first sentence names role + company, include one specific supply chain example, "
        "end with a direct ask for a call. Do NOT mention visa sponsorship."
    )
    return _llm(prompt, max_tokens=420) or _offline_cover_letter(profile, job)

def generate_cold_email(profile: dict, job: dict) -> str:
    name      = profile.get("candidate_name") or "Applicant"
    title     = job.get("title", "the role")
    company   = job.get("company", "your company")
    sc_skills = [s for s in (profile.get("skills") or []) if s in (
        "supply chain", "logistics", "procurement", "sap", "excel", "operations",
    )]
    skills_str = ", ".join(sc_skills[:4]) or ", ".join((profile.get("skills") or [])[:3])
    exp        = profile.get("years_of_experience_hint") or "some"
    prompt = (
        f"Write a short cold email from {name} to a recruiter at {company} about '{title}'. "
        f"Background: {exp} experience in supply chain / logistics, skills: {skills_str}. "
        "Rules: subject line first starting 'Subject:', under 120 words, "
        "sound human not corporate, no hollow openers, end with a low-friction ask for a call. "
        "Do NOT mention visa sponsorship."
    )
    return _llm(prompt, max_tokens=280) or _offline_cold_email(profile, job)

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
# JobSpy scraping  (LinkedIn, Indeed, Google only — Glassdoor removed)
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
    # Expanded to 4 keyword sets for wider coverage
    kw_sets = [
        keywords,
        SUPPLY_CHAIN_KEYWORDS[:5],
        SUPPLY_CHAIN_KEYWORDS[5:10],
        SUPPLY_CHAIN_BROAD[:3],
    ]
    tasks = [(site, kws) for kws in kw_sets for site in JOBSPY_SITES]
    with ThreadPoolExecutor(max_workers=12) as ex:  # raised from 8
        futures = {ex.submit(fn, site, kws, location, run): site for site, kws in tasks}
        for fut in as_completed(futures):
            try:
                all_jobs.extend(fut.result())
            except Exception as exc:
                add_log(run, "warning", f"[JobSpy] thread error: {exc}")
    return dedupe_jobs(all_jobs)

# ---------------------------------------------------------------------------
# Adzuna API scraper  (free, ~100 results/call, full descriptions)
# ---------------------------------------------------------------------------

def _adzuna(keywords: List[str], run: dict) -> List[dict]:
    """
    Adzuna public API — no key required for basic calls.
    Endpoint: https://api.adzuna.com/v1/api/jobs/gb/search/{page}
    """
    jobs = []
    search_term = " ".join(keywords[:3]).strip() or "supply chain logistics"
    add_log(run, "info", f"[Adzuna] '{search_term}'")
    for page in range(1, 4):   # 3 pages × ~50 results = up to 150 per keyword set
        try:
            resp = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}",
                params={
                    "app_id":       "a8bc89c5",   # public demo credentials
                    "app_key":      "6c04b7e6b1e81ff38fe9e2b3a5e2d9a7",
                    "results_per_page": 50,
                    "what":         search_term,
                    "where":        "UK",
                    "content-type": "application/json",
                },
                headers=REQUEST_HEADERS,
                timeout=(5, 20),
            )
            if resp.status_code != 200:
                break
            for item in resp.json().get("results", []):
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
            add_log(run, "warning", f"[Adzuna] page {page} skipped: {exc}")
            break
    add_log(run, "info", f"[Adzuna] → {len(jobs)} jobs")
    return jobs

# ---------------------------------------------------------------------------
# HTML board scraping
# ---------------------------------------------------------------------------

def _html_jobs(run, name, url, card_sels, title_sels, co_sels, loc_sels, sal_sels, desc_sels, base, limit):
    jobs = []
    try:
        add_log(run, "info", f"[HTML] Searching {name}...")
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=(5, 20))
        if resp.status_code != 200:
            add_log(run, "warning", f"[HTML] {name} returned {resp.status_code}")
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = []
        for s in card_sels:
            cards = soup.select(s)
            if cards:
                break
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
            def _t(sels):
                for s in sels:
                    el = card.select_one(s)
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
        add_log(run, "warning", f"[HTML] {name}: {exc}")
    return jobs

def _reed(kw, loc, run):
    q = quote_plus(" ".join(kw[:3]))
    l = quote_plus(loc or "united kingdom")
    return _html_jobs(run, "reed", f"https://www.reed.co.uk/jobs/{q}-jobs-in-{l}",
        ["article"], ["h2 a", "h3 a"], [".posted-by"], [".location"], [".salary"],
        [".description"], "https://www.reed.co.uk", HTML_SOURCE_CAP)

def _cvlibrary(kw, loc, run):
    q = quote_plus(" ".join(kw[:3]))
    l = quote_plus(loc or "United Kingdom")
    return _html_jobs(run, "cvlibrary",
        f"https://www.cv-library.co.uk/search-jobs?keywords={q}&geo={l}",
        ["li.job", "article.job"], ["h2 a", "h3 a"],
        [".company"], [".location"], [".salary"], [".description"],
        "https://www.cv-library.co.uk", HTML_SOURCE_CAP)

def _totaljobs(kw, loc, run):
    q = "-".join((" ".join(kw[:2]) or "logistics").split())
    l = "-".join((loc or "united-kingdom").split())
    return _html_jobs(run, "totaljobs",
        f"https://www.totaljobs.com/jobs/{q}/in-{l}",
        ["article", ".job-result"], ["h2 a", "h3 a"],
        [".company"], [".location"], [".salary"], [".description"],
        "https://www.totaljobs.com", HTML_SOURCE_CAP)

def _cwjobs(kw, loc, run):
    q = quote_plus(" ".join(kw[:3]))
    l = quote_plus(loc or "United Kingdom")
    return _html_jobs(run, "cwjobs",
        f"https://www.cwjobs.co.uk/jobs/{q}/in-{l}",
        ["article", ".job-result", "li.job"], ["h2 a", "h3 a"],
        [".company", ".employer"], [".location"], [".salary"], [".description"],
        "https://www.cwjobs.co.uk", HTML_SOURCE_CAP)

def _guardian(kw, run):
    q = quote_plus(" ".join(kw[:3]))
    return _html_jobs(run, "guardian",
        f"https://jobs.theguardian.com/jobs/{q}/",
        [".job-posting", "article", "li.job"], ["h2 a", "h3 a", ".job-title a"],
        [".company", ".employer"], [".location"], [".salary"], [".description"],
        "https://jobs.theguardian.com", HTML_SOURCE_CAP)

def _glassdoor_html(kw, run):
    """Direct Glassdoor HTML scraper — bypasses JobSpy entirely."""
    q  = quote_plus(" ".join(kw[:3]))
    url = f"https://www.glassdoor.co.uk/Job/united-kingdom-{q}-jobs-SRCH_IL.0,14_IN2_{q}.htm"
    return _html_jobs(run, "glassdoor_html",
        url,
        ["li.react-job-listing", "li[data-brandviews]", "article"],
        ["a.jobLink", "a[data-test='job-link']", "h2 a"],
        [".employerName", "[data-test='employer-name']"],
        [".loc", "[data-test='job-location']"],
        [".salary-estimate", "[data-test='detailSalary']"],
        [".jobDescriptionContent", ".desc"],
        "https://www.glassdoor.co.uk", HTML_SOURCE_CAP)

def _findajob(kw, run):
    q = quote_plus(" ".join(kw[:2]))
    return _html_jobs(run, "findajob",
        f"https://findajob.dwp.gov.uk/search?q={q}&where=UnitedKingdom&pp=25",
        ["div.search-result", "li.search-result"], ["h3 a", "h2 a"],
        [".employer"], [".location"], [".salary"], [".description"],
        "https://findajob.dwp.gov.uk", HTML_SOURCE_CAP)

def _nhs(kw, run):
    q = quote_plus(" ".join(kw[:2]))
    return _html_jobs(run, "nhs",
        f"https://www.jobs.nhs.uk/candidate/search/results?keyword={q}&location=United%20Kingdom&distance=200",
        ["li.vacancy", ".nhsuk-card"], ["h2 a", ".vacancy-title a"],
        [".employer"], [".location"], [".salary"], [".description"],
        "https://www.jobs.nhs.uk", HTML_SOURCE_CAP)

def _ukvisasponsorships(kw, run):
    q = quote_plus(" ".join(kw[:2]))
    return _html_jobs(run, "ukvisasponsorships",
        f"https://ukvisasponsorships.co.uk/jobs?q={q}",
        ["div.job", "article", ".job-card"], ["h2 a", "h3 a"],
        [".company"], [".location"], [".salary"], [".description"],
        "https://ukvisasponsorships.co.uk", HTML_SOURCE_CAP)

def scrape_all_html(keywords: List[str], location: str, run: dict) -> List[dict]:
    sc_kw    = keywords + SUPPLY_CHAIN_KEYWORDS[:4]
    broad_kw = SUPPLY_CHAIN_BROAD[:3]
    visa_kw  = ["visa sponsorship supply chain", "skilled worker logistics", "sponsorship procurement"]

    fetchers = [
        # Reed — 2 keyword sets
        lambda: _reed(sc_kw, location, run),
        lambda: _reed(broad_kw, location, run),
        # CV-Library
        lambda: _cvlibrary(sc_kw, location, run),
        # TotalJobs — 2 keyword sets
        lambda: _totaljobs(sc_kw, location, run),
        lambda: _totaljobs(broad_kw, location, run),
        # CWJobs (new)
        lambda: _cwjobs(sc_kw, location, run),
        lambda: _cwjobs(broad_kw, location, run),
        # Guardian Jobs (new)
        lambda: _guardian(sc_kw, run),
        # Glassdoor direct HTML (replaces broken JobSpy Glassdoor)
        lambda: _glassdoor_html(sc_kw, run),
        lambda: _glassdoor_html(broad_kw, run),
        # GOV.UK FindAJob
        lambda: _findajob(sc_kw, run),
        # NHS Jobs
        lambda: _nhs(sc_kw, run),
        # UK Visa Sponsorships — 2 keyword sets
        lambda: _ukvisasponsorships(sc_kw, run),
        lambda: _ukvisasponsorships(visa_kw, run),
        # Adzuna API — multiple keyword sets
        lambda: _adzuna(sc_kw, run),
        lambda: _adzuna(broad_kw, run),
        lambda: _adzuna(visa_kw, run),
    ]

    all_jobs: List[dict] = []
    with ThreadPoolExecutor(max_workers=10) as ex:  # raised from 6
        for fut in as_completed([ex.submit(fn) for fn in fetchers]):
            try:
                all_jobs.extend(fut.result())
            except Exception:
                pass
    return dedupe_jobs(all_jobs)

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

        update_run(run_id,
                   stage="📡 Searching LinkedIn, Indeed, Google, Reed, CV-Library, TotalJobs, "
                         "CWJobs, Guardian, Glassdoor, Adzuna, GOV.UK, NHS Jobs, UK Visa Sponsorships...",
                   progress_percent=5)

        with ThreadPoolExecutor(max_workers=2) as ex:
            f_js = ex.submit(scrape_all_jobspy, payload.keywords, payload.location, run)
            f_ht = ex.submit(scrape_all_html,   payload.keywords, payload.location, run)
            jobspy_jobs = f_js.result()
            html_jobs   = f_ht.result()

        all_jobs = dedupe_jobs(jobspy_jobs + html_jobs)
        all_jobs = apply_filters(all_jobs, blacklist, whitelist, spons_required)
        update_run(run_id, jobs_scanned=len(all_jobs), progress_percent=50)
        add_log(run, "info",
                f"Total after dedup+filter: {len(all_jobs)} "
                f"(jobspy={len(jobspy_jobs)} html/api={len(html_jobs)})")

        if not all_jobs:
            add_log(run, "warning", "No live jobs found — showing sample jobs")
            all_jobs = FALLBACK_JOBS[:]

        update_run(run_id,
                   stage="🤖 Scoring jobs and generating cover letters...",
                   progress_percent=50)
        matched = 0
        for idx, job in enumerate(all_jobs):
            score_data = ai_fit_score(job, profile, payload.keywords)
            job["fit_score"] = score_data["fit_score"]
            job["fit_level"] = score_data["fit_level"]

            if score_data["fit_score"] >= 25 and job.get("sponsorship_status") != "no":
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
