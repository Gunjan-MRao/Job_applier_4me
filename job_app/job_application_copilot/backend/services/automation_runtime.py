"""
automation_runtime.py  –  streaming apply pipeline

LLM priority (all free first):
  1. Google Gemini 1.5 Flash  — FREE, 1500 req/day  (aistudio.google.com)
  2. HuggingFace Inference API — FREE tier           (huggingface.co)
  3. Smart offline template   — ZERO API, always works
  4. OpenAI / Anthropic       — optional paid fallback

Key behaviours:
- No max_jobs cap
- Stream-apply: cover letter + cold email + resume guidance per match immediately
- Parallel scraping all sources
- Sponsorship-aware filtering
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
JOBSPY_MAX_PER_SOURCE = 1000
HTML_SOURCE_CAP = 500

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
     "description": "Graduate logistics, transport planning, warehouse coordination, supply chain.",
     "source": "fallback", "recruiter_email": None},
    {"title": "Supply Chain Analyst", "company": "Amazon", "location": "United Kingdom",
     "url": "https://www.amazon.jobs", "sponsorship_status": "unknown",
     "description": "Supply chain analyst, reporting, Excel, forecasting, planning.",
     "source": "fallback", "recruiter_email": None},
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
        "applied_jobs": [],
        "created_at": now_iso(),
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
    negative = ["no sponsorship", "unable to sponsor", "must have right to work",
                "no visa sponsorship", "cannot sponsor", "not able to sponsor",
                "without sponsorship", "you must already have the right to work",
                "must already hold", "no tier 2"]
    positive = ["visa sponsorship", "sponsorship available", "skilled worker visa",
                "certificate of sponsorship", "cos available", "we can sponsor",
                "eligible for sponsorship", "sponsorship may be available", "tier 2"]
    if any(x in text for x in negative):
        return "no"
    if any(x in text for x in positive):
        return "yes"
    return "unknown"

# ---------------------------------------------------------------------------
# AI fit scoring
# ---------------------------------------------------------------------------

def ai_fit_score(job: dict, profile: Optional[dict], keywords: List[str]) -> dict:
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
                    "weights": {"title": 25, "skills": 35, "seniority": 15,
                                "location": 10, "sponsorship": 10, "education": 5},
                    "require_sponsorship_if_needed": False,
                    "reject_when_sponsorship_unknown": False,
                    "use_max_seniority_gap": True,
                    "max_seniority_gap": 2,
                    "location_strict": False,
                    "work_mode_strict": False,
                    "minimum_fit_score": 30,
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
                    "reasons": result.get("reasons", []), "gaps": result.get("gaps", [])}
        except Exception:
            pass
    combined = f"{job.get('title', '')} {job.get('description', '')}"
    haystack = combined.lower()
    raw = sum(1 for kw in keywords if kw and kw.strip().lower() in haystack)
    score = min(int(raw / max(len(keywords), 1) * 100), 100)
    level = "strong" if score >= 70 else ("moderate" if score >= 40 else "weak")
    return {"fit_score": score, "fit_level": level, "reasons": [], "gaps": []}

# ---------------------------------------------------------------------------
# LLM — FREE first, paid optional, offline always works
# ---------------------------------------------------------------------------

def _gemini(prompt: str, max_tokens: int = 500) -> Optional[str]:
    """Google Gemini 1.5 Flash — FREE, 1500 requests/day."""
    key = settings.gemini_api_key
    if not key:
        return None
    try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
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
    """HuggingFace Inference API — FREE tier, no credit card needed."""
    key = settings.hf_api_key
    if not key:
        return None
    try:
        # Use Mistral-7B-Instruct — excellent free model
        url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
        headers = {"Authorization": f"Bearer {key}"}
        body = {
            "inputs": prompt,
            "parameters": {"max_new_tokens": max_tokens, "temperature": 0.75,
                           "return_full_text": False},
        }
        resp = requests.post(url, headers=headers, json=body, timeout=60)
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
    """Try free APIs first, then paid, return None to trigger offline fallback."""
    return (
        _gemini(prompt, max_tokens)
        or _huggingface(prompt, max_tokens)
        or _openai_llm(prompt, max_tokens)
        or _anthropic_llm(prompt, max_tokens)
    )


# ---------------------------------------------------------------------------
# Smart offline cover letter (no API needed — still personalised)
# ---------------------------------------------------------------------------

def _offline_cover_letter(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    skills = profile.get("skills") or []
    exp = profile.get("years_of_experience_hint") or "relevant"
    roles = profile.get("likely_roles") or []
    top_skill = skills[0] if skills else "my core skills"
    second_skill = skills[1] if len(skills) > 1 else ""
    skill_line = f"{top_skill} and {second_skill}" if second_skill else top_skill
    role_context = f"My background in {roles[0]}" if roles else "My background"

    # Extract a hint from job description to make it feel specific
    desc = (job.get("description") or "").lower()
    context_line = ""
    if "excel" in desc:
        context_line = "I have strong Excel and data analysis skills which I understand are central to this role."
    elif "supply chain" in desc or "logistics" in desc:
        context_line = "I have hands-on exposure to supply chain processes and am eager to grow further in this area."
    elif "team" in desc or "collaboration" in desc:
        context_line = "I thrive in collaborative environments and have consistently delivered results as part of cross-functional teams."
    elif "customer" in desc:
        context_line = "I have experience working in customer-facing contexts and understand the importance of service excellence."
    else:
        context_line = f"I am confident my background in {skill_line} aligns well with what you are looking for."

    return (
        f"Dear Hiring Team at {company},\n\n"
        f"I was genuinely excited to come across the {title} opportunity at {company} "
        f"and wanted to apply with enthusiasm.\n\n"
        f"{role_context} has given me {exp} of experience in {skill_line}. "
        f"{context_line}\n\n"
        f"I am currently seeking a role where I can contribute from day one while "
        f"continuing to grow. I would love the opportunity to speak with you — "
        f"would you be open to a 20-minute call this week or next?\n\n"
        f"Thank you for your time.\n\nKind regards,\n{name}"
    )


def _offline_cold_email(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    skills = profile.get("skills") or []
    exp = profile.get("years_of_experience_hint") or "relevant"
    top_skills = ", ".join(skills[:3]) if skills else "relevant skills"

    return (
        f"Subject: {title} — {name}\n\n"
        f"Hi,\n\n"
        f"I noticed the {title} role at {company} and wanted to reach out directly "
        f"rather than just submit an application into the void.\n\n"
        f"I have {exp} experience with {top_skills}. "
        f"I am motivated, quick to learn, and looking to make a real contribution at {company}.\n\n"
        f"Would you have 15 minutes for a quick call this week?\n\n"
        f"Best,\n{name}"
    )


# ---------------------------------------------------------------------------
# Public generation functions
# ---------------------------------------------------------------------------

def generate_cover_letter(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    skills = ", ".join((profile.get("skills") or [])[:8])
    exp = profile.get("years_of_experience_hint") or "relevant"
    desc_snip = (job.get("description") or "")[:400]
    prompt = (
        f"Write a concise, genuine cover letter for {name} applying for '{title}' at {company}. "
        f"Candidate: {exp} experience, skills: {skills}. "
        f"Job excerpt: {desc_snip}. "
        "Rules: under 220 words, no filler phrases like 'I am writing to express', "
        "no brackets, first sentence names the role+company, one achievement example, "
        "end with a specific ask for a call."
    )
    return _llm(prompt, max_tokens=420) or _offline_cover_letter(profile, job)


def generate_cold_email(profile: dict, job: dict) -> str:
    name = profile.get("candidate_name") or "Applicant"
    title = job.get("title", "the role")
    company = job.get("company", "your company")
    skills = ", ".join((profile.get("skills") or [])[:5])
    exp = profile.get("years_of_experience_hint") or "relevant"
    prompt = (
        f"Write a short humanised cold email from {name} to recruiter at {company} "
        f"about '{title}'. Background: {exp} exp, skills: {skills}. "
        "Rules: subject line first starting 'Subject:', under 120 words, "
        "sound human not a bot, no hollow openers, end with a low-friction ask."
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
# JobSpy scraping
# ---------------------------------------------------------------------------

def _safe_val(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def jobspy_scrape_site(site: str, keywords: List[str], location: str, run: dict) -> List[dict]:
    search_term = " ".join(keywords).strip() or "supply chain logistics"
    add_log(run, "info", f"[JobSpy] {site} → '{search_term}' in '{location}'")
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
                "title": _safe_val(row.get("title")) or "Unknown title",
                "company": _safe_val(row.get("company")) or "Unknown company",
                "location": _safe_val(row.get("location")) or location,
                "salary": str(_safe_val(row.get("min_amount")) or ""),
                "url": _safe_val(row.get("job_url")) or "",
                "sponsorship_status": classify_sponsorship(desc),
                "description": desc,
                "source": site,
                "date_posted": str(_safe_val(row.get("date_posted")) or ""),
                "recruiter_email": _safe_val(row.get("emails")),
            })
        add_log(run, "info", f"[JobSpy] {site} → {len(rows)} jobs")
        return rows
    except Exception as exc:
        add_log(run, "warning", f"[JobSpy] {site} failed: {exc}")
        return []


def jobspy_fallback_http(site: str, keywords: List[str], location: str, run: dict) -> List[dict]:
    search_term = " ".join(keywords).strip() or "supply chain logistics"
    params = {"site_name": site, "search_term": search_term,
               "location": location or "United Kingdom",
               "results_wanted": JOBSPY_MAX_PER_SOURCE, "offset": 0}
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
                "salary": str(row.get("min_amount") or ""),
                "url": row.get("job_url") or "",
                "sponsorship_status": classify_sponsorship(desc),
                "description": desc,
                "source": site,
                "recruiter_email": None,
            })
        return rows
    except Exception as exc:
        add_log(run, "warning", f"[JobSpy-HTTP] {site} failed: {exc}")
        return []


def scrape_all_jobspy(keywords: List[str], location: str, run: dict) -> List[dict]:
    fn = jobspy_scrape_site if JOBSPY_AVAILABLE else jobspy_fallback_http
    all_jobs: List[dict] = []
    with ThreadPoolExecutor(max_workers=len(JOBSPY_SITES)) as ex:
        futures = {ex.submit(fn, site, keywords, location, run): site for site in JOBSPY_SITES}
        for fut in as_completed(futures):
            try:
                all_jobs.extend(fut.result())
            except Exception as exc:
                add_log(run, "warning", f"[JobSpy] thread error: {exc}")
    return dedupe_jobs(all_jobs)


# ---------------------------------------------------------------------------
# HTML board scraping
# ---------------------------------------------------------------------------

def _html_jobs(run, name, url, card_sels, title_sels, co_sels, loc_sels, sal_sels, desc_sels, base, limit):
    jobs = []
    try:
        add_log(run, "info", f"[HTML] {name}")
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=(5, 20))
        if resp.status_code != 200:
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
                "title": title_text, "company": _t(co_sels) or "Unknown",
                "location": _t(loc_sels) or "United Kingdom",
                "salary": _t(sal_sels), "url": job_url,
                "sponsorship_status": classify_sponsorship(desc),
                "description": desc, "source": name, "recruiter_email": None,
            })
            if len(jobs) >= limit:
                break
        add_log(run, "info", f"[HTML] {name} → {len(jobs)} jobs")
    except Exception as exc:
        add_log(run, "warning", f"[HTML] {name}: {exc}")
    return jobs


def _reed(kw, loc, run):
    q, l = quote_plus(" ".join(kw)), quote_plus(loc or "united kingdom")
    return _html_jobs(run, "reed", f"https://www.reed.co.uk/jobs/{q}-jobs-in-{l}",
        ["article"], ["h2 a", "h3 a"], [".posted-by"], [".location"], [".salary"],
        [".description"], "https://www.reed.co.uk", HTML_SOURCE_CAP)

def _cvlibrary(kw, loc, run):
    q, l = quote_plus(" ".join(kw)), quote_plus(loc or "United Kingdom")
    return _html_jobs(run, "cvlibrary",
        f"https://www.cv-library.co.uk/search-jobs?keywords={q}&geo={l}",
        ["li.job", "article.job"], ["h2 a", "h3 a"],
        [".company"], [".location"], [".salary"], [".description"],
        "https://www.cv-library.co.uk", HTML_SOURCE_CAP)

def _totaljobs(kw, loc, run):
    q = "-".join((" ".join(kw) or "logistics").split())
    l = "-".join((loc or "united-kingdom").split())
    return _html_jobs(run, "totaljobs",
        f"https://www.totaljobs.com/jobs/{q}/in-{l}",
        ["article", ".job-result"], ["h2 a", "h3 a"],
        [".company"], [".location"], [".salary"], [".description"],
        "https://www.totaljobs.com", HTML_SOURCE_CAP)

def _findajob(kw, run):
    q = quote_plus(" ".join(kw))
    return _html_jobs(run, "findajob",
        f"https://findajob.dwp.gov.uk/search?q={q}&where=UnitedKingdom&pp=25",
        ["div.search-result", "li.search-result"], ["h3 a", "h2 a"],
        [".employer"], [".location"], [".salary"], [".description"],
        "https://findajob.dwp.gov.uk", HTML_SOURCE_CAP)

def _nhs(kw, run):
    q = quote_plus(" ".join(kw))
    return _html_jobs(run, "nhs",
        f"https://www.jobs.nhs.uk/candidate/search/results?keyword={q}&location=United%20Kingdom&distance=200",
        ["li.vacancy", ".nhsuk-card"], ["h2 a", ".vacancy-title a"],
        [".employer"], [".location"], [".salary"], [".description"],
        "https://www.jobs.nhs.uk", HTML_SOURCE_CAP)

def _ukvisasponsorships(kw, run):
    q = quote_plus(" ".join(kw))
    return _html_jobs(run, "ukvisasponsorships",
        f"https://ukvisasponsorships.co.uk/jobs?q={q}",
        ["div.job", "article", ".job-card"], ["h2 a", "h3 a"],
        [".company"], [".location"], [".salary"], [".description"],
        "https://ukvisasponsorships.co.uk", HTML_SOURCE_CAP)


def scrape_all_html(keywords: List[str], location: str, run: dict) -> List[dict]:
    fetchers = [
        lambda: _reed(keywords, location, run),
        lambda: _cvlibrary(keywords, location, run),
        lambda: _totaljobs(keywords, location, run),
        lambda: _findajob(keywords, run),
        lambda: _nhs(keywords, run),
        lambda: _ukvisasponsorships(keywords, run),
    ]
    all_jobs: List[dict] = []
    with ThreadPoolExecutor(max_workers=len(fetchers)) as ex:
        for fut in as_completed([ex.submit(fn) for fn in fetchers]):
            try:
                all_jobs.extend(fut.result())
            except Exception:
                pass
    return dedupe_jobs(all_jobs)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def apply_filters(jobs, blacklist, whitelist):
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
        out.append(job)
    return out


# ---------------------------------------------------------------------------
# Stream apply
# ---------------------------------------------------------------------------

def stream_apply_job(job: dict, profile: Optional[dict], keywords: List[str],
                     auto_apply: bool, run: dict, run_id: str) -> None:
    title = job.get("title", "?")
    company = job.get("company", "?")
    fit = job.get("fit_score", 0)
    entry = {
        "title": title, "company": company,
        "url": job.get("url", ""), "fit_score": fit,
        "sponsorship_status": job.get("sponsorship_status", "unknown"),
        "source": job.get("source", ""),
        "cover_letter": None, "cold_email": None, "resume_guidance": None,
    }
    if auto_apply and profile:
        try:
            entry["resume_guidance"] = generate_resume_tailoring(
                profile, {"title": title, "company": company,
                          "description": job.get("description", ""),
                          "skills": [], "url": job.get("url", "")})
        except Exception as exc:
            add_log(run, "warning", f"Tailoring failed for {title}: {exc}")
        try:
            entry["cover_letter"] = generate_cover_letter(profile, job)
        except Exception as exc:
            add_log(run, "warning", f"Cover letter failed for {title}: {exc}")
        try:
            entry["cold_email"] = generate_cold_email(profile, job)
        except Exception as exc:
            add_log(run, "warning", f"Cold email failed for {title}: {exc}")
        add_log(run, "info",
                f"✅ {title} @ {company} | fit={fit}% | "
                f"cl={'yes' if entry['cover_letter'] else 'no'} | "
                f"email={'yes' if entry['cold_email'] else 'no'}")
    else:
        add_log(run, "info", f"📌 Matched: {title} @ {company} | fit={fit}%")
    with RUN_LOCK:
        run_obj = RUNS.get(run_id)
        if run_obj:
            run_obj["applied_jobs"].append(entry)
            run_obj["jobs_applied"] = len(run_obj["applied_jobs"])
            run_obj["top_matches"] = sorted(
                run_obj["applied_jobs"],
                key=lambda x: x.get("fit_score", 0), reverse=True
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
                f"Pipeline start | email={payload.candidate_email} | "
                f"keywords={payload.keywords} | location={payload.location}")
        profile = getattr(payload, "resume_profile", None)
        blacklist = getattr(payload, "company_blacklist", []) or []
        whitelist = getattr(payload, "company_whitelist", []) or []
        auto_apply = getattr(payload, "auto_apply", True)

        update_run(run_id, stage="scraping_all_sources", progress_percent=5)
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_js = ex.submit(scrape_all_jobspy, payload.keywords, payload.location, run)
            f_ht = ex.submit(scrape_all_html, payload.keywords, payload.location, run)
            jobspy_jobs = f_js.result()
            html_jobs = f_ht.result()

        all_jobs = dedupe_jobs(jobspy_jobs + html_jobs)
        all_jobs = apply_filters(all_jobs, blacklist, whitelist)
        update_run(run_id, jobs_scanned=len(all_jobs), progress_percent=50)
        add_log(run, "info", f"Total: {len(all_jobs)} unique jobs (jobspy={len(jobspy_jobs)}, html={len(html_jobs)})")
        if not all_jobs:
            add_log(run, "warning", "No live jobs — using fallback samples")
            all_jobs = FALLBACK_JOBS[:]

        update_run(run_id, stage="scoring_and_applying", progress_percent=50)
        matched = 0
        for idx, job in enumerate(all_jobs):
            score_data = ai_fit_score(job, profile, payload.keywords)
            job["fit_score"] = score_data["fit_score"]
            job["fit_level"] = score_data["fit_level"]
            if score_data["fit_score"] >= 30 and job.get("sponsorship_status") != "no":
                matched += 1
                update_run(run_id, jobs_matched=matched)
                stream_apply_job(job, profile, payload.keywords, auto_apply, run, run_id)
            if idx % 20 == 0:
                pct = 50 + int((idx / max(len(all_jobs), 1)) * 45)
                update_run(run_id, progress_percent=min(pct, 95), current_url=job.get("url"))

        final_run = get_run(run_id) or {}
        summary = {
            "keywords": payload.keywords, "location": payload.location,
            "jobs_seen": len(all_jobs), "matched_jobs": matched,
            "applied_jobs": len(final_run.get("applied_jobs", [])),
            "jobspy_direct": JOBSPY_AVAILABLE,
            "llm_used": bool(settings.gemini_api_key or settings.hf_api_key
                             or settings.openai_api_key or settings.anthropic_api_key),
            "top_matches": [
                {"title": j["title"], "company": j["company"],
                 "fit_score": j.get("fit_score"), "url": j["url"]}
                for j in sorted(final_run.get("applied_jobs", []),
                                key=lambda x: x.get("fit_score", 0), reverse=True)[:10]
            ],
        }
        update_run(run_id, status="completed", stage="completed",
                   progress_percent=100, current_url=None, result_summary=summary)
        add_log(run, "info",
                f"✅ Done: {len(all_jobs)} scanned, {matched} matched, "
                f"{summary['applied_jobs']} processed")
    except Exception as exc:
        run = get_run(run_id)
        if run:
            update_run(run_id, status="failed", stage="failed", current_url=None)
            add_log(run, "error", f"Pipeline crashed: {exc}")


def start_run_thread(payload) -> dict:
    run = create_run(payload)
    threading.Thread(
        target=run_automation_pipeline, args=(run["run_id"], payload), daemon=True
    ).start()
    return run
