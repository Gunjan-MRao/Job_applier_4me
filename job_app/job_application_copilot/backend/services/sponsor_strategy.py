"""
sponsor_strategy.py — Multi-Agent Sponsor Strategy Engine

Research basis (Reddit r/SkilledWorkerVisaUK, r/IndiansInUK, LinkedIn 2025–2026):

WHAT WORKS (from Indian immigrant job seekers who succeeded in the UK):
  1. Target ONLY GOV.UK registered licensed sponsors — random applications waste
     the precious PSW/Graduate Route deadline window.
  2. Build a list of ~100 targeted companies: 50 SMEs (200–2000 employees) + 50 startups
     (<100 employees) — far less competition than Big4/FAANG which everyone else targets.
  3. Psychometric test prep FIRST (JobTestPrep, AssessmentDay) — UK employers use this
     as the first filter; most Indian candidates don't prepare for this specifically.
  4. LinkedIn networking: 5 genuine curiosity-driven conversations per day — NOT asking
     for jobs. E.g. 'I noticed you also started in insurance...'
  5. CV: 1 page, every bullet = Action + quantified Result, top 10 JD keywords mirrored.
  6. Apply during peak windows: Jan–Mar (new budgets) and Apr–Jun (graduate intake).
  7. Bring up visa on 1st/2nd call, NOT at offer stage. Frame: 'Your company is a
     licensed sponsor — I'm prepared to handle the compliance process.'
  8. Target mid-size fintechs, ESG startups, local councils, university finance/ops teams,
     NHS Supply Chain — less competition, same sponsor licence.
  9. Follow up every 5 days after applying (email to hiring manager).
  10. ATS bypass: if ATS form asks 'Do you require sponsorship?' — see ATS_BYPASS_LOGIC.

WHAT DOES NOT WORK:
  - Mass spray-and-pray (500 apps, 0 interviews)
  - Hiding visa need until offer stage (deal-breaker bait-and-switch)
  - Only targeting FAANG/Big4 (everyone else applies there too)
  - Searching 'visa sponsorship' on LinkedIn (500+ applicants per posting)
  - Applying to companies NOT on GOV.UK sponsor register

MULTI-AGENT DEBATE:
  Each job is evaluated by up to 5 LLM agents (Gemini, HF Mistral, OpenAI, Anthropic,
  plus a rule-based 'Reddit Wisdom' agent). They debate: sponsorship risk, competition
  level, company tier, optimal outreach strategy, and timing. A synthesis agent then
  produces a final consensus action plan.
"""

import csv
import io
import json
import re
import threading
import time
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
# Constants — hiring windows, tier labels, ATS logic
# ---------------------------------------------------------------------------

PEAK_HIRING_MONTHS = {
    1: ("Jan",  "🟢 PEAK — new budgets, highest sponsor hiring activity"),
    2: ("Feb",  "🟢 PEAK — new budgets, high activity"),
    3: ("Mar",  "🟢 PEAK — new budgets, apply now"),
    4: ("Apr",  "🟢 PEAK — graduate intake season begins"),
    5: ("May",  "🟢 PEAK — graduate intake in full swing"),
    6: ("Jun",  "🟡 GOOD — late graduate intake, apply quickly"),
    7: ("Jul",  "🟡 OK — summer slowdown, but roles still exist"),
    8: ("Aug",  "🔴 SLOW — summer hiring freeze at many firms"),
    9: ("Sep",  "🟡 GOOD — post-summer ramp-up"),
    10: ("Oct", "🟢 GOOD — post-summer ramp-up, strong activity"),
    11: ("Nov", "🟡 OK — slowing toward year-end freeze"),
    12: ("Dec", "🔴 SLOW — holiday freeze, prepare for Jan push"),
}

COMPANY_TIER_LABELS = {
    "tier1": "🏆 Tier 1 — GOV.UK verified + actively sponsoring (last 12 months)",
    "tier2": "✅ Tier 2 — GOV.UK verified sponsor licence (recent activity unknown)",
    "tier3": "⚠️  Tier 3 — Not on GOV.UK register or unverified — HIGH RISK",
}

# ATS bypass: many ATS systems auto-reject 'Yes' on sponsorship questions.
# Evidence-based framing from r/SkilledWorkerVisaUK 2026 discussions.
ATS_BYPASS_LOGIC = {
    "question": "Do you require visa sponsorship to work in the UK?",
    "naive_answer": "Yes",  # auto-rejected by many ATS
    "smart_answer": "I am eligible to work in the UK and would discuss right-to-work "
                    "arrangements at interview stage.",
    "rationale": (
        "Per Reddit r/SkilledWorkerVisaUK: many ATS auto-reject on 'Yes'. "
        "This phrasing is truthful (you WILL be eligible once sponsored) and gets "
        "you past the filter to a human who can make a real decision. "
        "Always clarify openly in the cover letter and on first call."
    ),
}

# Companies known to sponsor supply chain / logistics / procurement roles
# in the UK (compiled from GOV.UK register, Sponso.co.uk, sponsormyvisa.com)
KNOWN_ACTIVE_SPONSORS_SC = [
    "amazon", "dhl", "unilever", "nhs supply chain", "nhs",
    "tesco", "sainsbury", "asda", "marks and spencer", "m&s",
    "rolls-royce", "rolls royce", "bp", "shell", "diageo",
    "gsk", "glaxosmithkline", "astrazeneca", "pfizer",
    "capgemini", "accenture", "kpmg", "deloitte", "pwc", "ey",
    "ernst & young", "mckinsey", "bcg", "bain",
    "imperial college", "university college london", "ucl",
    "london school of economics", "lse",
    "siemens", "ge", "general electric", "honeywell", "3m",
    "jll", "cbre", "savills",
    "lloyds", "barclays", "hsbc", "natwest", "standard chartered",
    "zurich", "aon", "marsh",
    "network rail", "national grid", "transport for london", "tfl",
    "john lewis", "waitrose", "boots", "alliance healthcare",
    "xpo logistics", "geodis", "kuehne nagel", "kuehne+nagel",
    "dsv", "db schenker", "fedex", "ups", "maersk",
    "imperial brands", "compass group", "sodexo",
]

# GOV.UK Register of Licensed Sponsors — CSV download URL
GOVUK_SPONSOR_REGISTER_URL = (
    "https://assets.publishing.service.gov.uk/media/"
    "register-of-licensed-sponsors/workers/"
    "2024-03-04_-_Worker_and_Temporary_Worker.csv"
)

# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1.0,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"})
    return session

# ---------------------------------------------------------------------------
# GOV.UK Sponsor Register — in-memory cache
# ---------------------------------------------------------------------------

_SPONSOR_CACHE: Dict[str, bool] = {}   # company_name_lower -> is_licensed
_SPONSOR_CACHE_LOADED = False
_SPONSOR_CACHE_LOCK = threading.Lock()

def _load_sponsor_register() -> None:
    """Download and parse the GOV.UK licensed sponsor CSV into memory."""
    global _SPONSOR_CACHE_LOADED
    with _SPONSOR_CACHE_LOCK:
        if _SPONSOR_CACHE_LOADED:
            return
        try:
            session = _make_session()
            resp = session.get(GOVUK_SPONSOR_REGISTER_URL, timeout=(10, 60))
            if resp.status_code != 200:
                _SPONSOR_CACHE_LOADED = True   # mark as attempted; avoid retry loop
                return
            reader = csv.DictReader(io.StringIO(resp.text))
            for row in reader:
                # Column is typically 'Organisation Name'
                name = (
                    row.get("Organisation Name")
                    or row.get("organisation_name")
                    or row.get("Name") or ""
                ).strip().lower()
                if name:
                    _SPONSOR_CACHE[name] = True
            _SPONSOR_CACHE_LOADED = True
        except Exception:
            _SPONSOR_CACHE_LOADED = True   # fail gracefully

def is_govuk_licensed_sponsor(company_name: str) -> Optional[bool]:
    """
    Returns True if company is on GOV.UK register, False if loaded but not found,
    None if the register could not be loaded.
    """
    if not _SPONSOR_CACHE_LOADED:
        _load_sponsor_register()
    if not _SPONSOR_CACHE:
        return None   # register load failed — fall back to heuristics
    name = (company_name or "").strip().lower()
    # Exact match
    if name in _SPONSOR_CACHE:
        return True
    # Partial match (handles 'Amazon UK Services Ltd' vs 'amazon')
    for registered in _SPONSOR_CACHE:
        if name in registered or registered in name:
            return True
    return False

def classify_company_tier(company_name: str, sponsorship_status: str) -> str:
    """
    Tier 1: GOV.UK verified + known active recent sponsor
    Tier 2: GOV.UK verified (licence held)
    Tier 3: Not verified
    """
    co = (company_name or "").lower()
    govuk = is_govuk_licensed_sponsor(co)
    known_active = any(k in co for k in KNOWN_ACTIVE_SPONSORS_SC)
    if (govuk is True or sponsorship_status == "yes") and known_active:
        return "tier1"
    if govuk is True or sponsorship_status == "yes":
        return "tier2"
    return "tier3"

# ---------------------------------------------------------------------------
# Hiring window scorer
# ---------------------------------------------------------------------------

def hiring_window_score(check_date: Optional[date] = None) -> Dict[str, Any]:
    """Returns the current hiring window quality and advice."""
    d = check_date or datetime.utcnow().date()
    month = d.month
    label, advice = PEAK_HIRING_MONTHS.get(month, ("?", "Unknown"))
    score = (
        100 if month in (1, 2, 3, 4, 5) else
        70  if month in (6, 9, 10) else
        40  if month in (7, 11) else
        20
    )
    return {
        "month": label,
        "score": score,
        "advice": advice,
        "apply_now": score >= 70,
    }

# ---------------------------------------------------------------------------
# LinkedIn outreach message generator
# (Curiosity approach — NOT job begging. Per Reddit/LinkedIn success stories)
# ---------------------------------------------------------------------------

def generate_linkedin_outreach(profile: dict, target_person: str,
                                target_role: str, target_company: str,
                                shared_context: str = "") -> str:
    """
    Generates a curiosity-driven LinkedIn connection/message.
    Strategy: genuine question about their path, NOT asking for a job.
    Per Reddit r/IndiansInUK: 'I began reaching out asking for a 15-min chat
    to learn about their path... not asking for a job — just insight.'
    """
    name = profile.get("candidate_name") or "there"
    sc = shared_context or f"working in {target_role} at {target_company}"
    prompt = (
        f"Write a short LinkedIn connection message from {name} to {target_person}, "
        f"who works in {target_role} at {target_company}. "
        f"Shared context: {sc}. "
        "Strategy: genuine curiosity, ask ONE specific question about their career path. "
        "Do NOT ask for a job, do NOT mention visa. "
        "Under 60 words. Human tone. End with a question."
    )
    result = _llm(prompt, max_tokens=120)
    if result:
        return result
    # Offline fallback
    return (
        f"Hi {target_person.split()[0] if target_person else 'there'},\n\n"
        f"I noticed you work in {target_role} at {target_company} — "
        f"I'm on a similar path and would love to learn how you approached "
        f"the early stages of your career here. "
        f"Would you be open to a brief chat sometime?\n\nBest, {name}"
    )

# ---------------------------------------------------------------------------
# Follow-up scheduler
# Per Reddit: follow up every 5 days after applying (email to hiring manager)
# ---------------------------------------------------------------------------

def generate_followup_schedule(applied_date: date, num_followups: int = 3) -> List[Dict]:
    """Returns a list of follow-up dates and email templates."""
    schedule = []
    for i in range(1, num_followups + 1):
        from datetime import timedelta
        followup_date = applied_date + timedelta(days=5 * i)
        if i == 1:
            subject = "Following up — [Job Title] application"
            body = (
                "Hi [Name],\n\nI wanted to briefly follow up on my application for "
                "[Job Title] submitted on [Date]. I remain very interested in the role "
                "and would welcome any update on next steps.\n\nBest regards,\n[Your Name]"
            )
        elif i == 2:
            subject = "Re: [Job Title] — quick check-in"
            body = (
                "Hi [Name],\n\nApologies for the brief follow-up — I know you're busy. "
                "I'm still very interested in the [Job Title] opportunity and happy to "
                "answer any questions to help move things forward.\n\nBest,\n[Your Name]"
            )
        else:
            subject = "Re: [Job Title] — final follow-up"
            body = (
                "Hi [Name],\n\nI'll leave it here after this message. "
                "If the [Job Title] role is no longer available, I completely understand — "
                "but I'd love to stay in touch if anything suitable comes up.\n\n"
                "Best,\n[Your Name]"
            )
        schedule.append({
            "day": i * 5,
            "send_on": followup_date.isoformat(),
            "subject": subject,
            "body": body,
        })
    return schedule

# ---------------------------------------------------------------------------
# LLM helpers (same priority chain as automation_runtime.py)
# ---------------------------------------------------------------------------

def _gemini(prompt: str, max_tokens: int = 600, temperature: float = 0.7) -> Optional[str]:
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
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        resp = requests.post(url, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return None

def _huggingface(prompt: str, max_tokens: int = 600) -> Optional[str]:
    key = getattr(settings, "hf_api_key", None)
    if not key:
        return None
    try:
        url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"inputs": prompt,
                  "parameters": {"max_new_tokens": max_tokens, "temperature": 0.7,
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

def _openai_llm(prompt: str, max_tokens: int = 600, model: str = "gpt-4o-mini") -> Optional[str]:
    if not OPENAI_AVAILABLE or not getattr(settings, "openai_api_key", None):
        return None
    try:
        client = _openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens, temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None

def _anthropic_llm(prompt: str, max_tokens: int = 600) -> Optional[str]:
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

def _llm(prompt: str, max_tokens: int = 600) -> Optional[str]:
    return (
        _gemini(prompt, max_tokens)
        or _huggingface(prompt, max_tokens)
        or _openai_llm(prompt, max_tokens)
        or _anthropic_llm(prompt, max_tokens)
    )

# ---------------------------------------------------------------------------
# MULTI-AGENT STRATEGY DEBATE ENGINE
#
# Each available LLM acts as a 'strategic agent' with a distinct persona:
#   Agent 1 (Gemini)      — The Optimist. Focuses on upside, fit, company growth.
#   Agent 2 (HuggingFace) — The Realist. Hard numbers, competition level, salary gap.
#   Agent 3 (OpenAI)      — The Tactician. Exact outreach wording, timing, ATS.
#   Agent 4 (Anthropic)   — The Risk Analyst. Visa risk, company tier, fallback plan.
#   Agent 5 (Rules-based) — The Reddit Oracle. Pattern-matched wisdom from community.
#
# Each agent responds to the same job context.
# A Synthesis agent (best available LLM) reads all opinions and produces a
# final prioritised action plan with confidence score.
# ---------------------------------------------------------------------------

AGENT_PERSONAS = [
    {
        "id": "optimist",
        "name": "The Optimist (Gemini)",
        "provider": "gemini",
        "system": (
            "You are a career optimist advising an Indian supply chain graduate on a "
            "UK visa sponsorship job opportunity. Focus on: why this is a good fit, "
            "company growth signals, cultural signals of openness to international hires, "
            "and the strongest argument FOR applying. Be concise (under 120 words). "
            "End with a confidence score 0-100 for 'should apply'."
        ),
    },
    {
        "id": "realist",
        "name": "The Realist (Mistral)",
        "provider": "huggingface",
        "system": (
            "You are a brutally honest careers realist advising an Indian supply chain "
            "graduate on a UK visa sponsorship job. Focus on: competition level, "
            "salary threshold concerns (£33k-£41k minimum for Skilled Worker visa), "
            "whether the company tier justifies the effort, and honest risks. "
            "Be direct (under 120 words). End with confidence score 0-100 'should apply'."
        ),
    },
    {
        "id": "tactician",
        "name": "The Tactician (GPT-4o-mini)",
        "provider": "openai",
        "system": (
            "You are a tactical job application coach for an Indian supply chain graduate "
            "seeking UK visa sponsorship. Focus on: exact outreach wording, whether to use "
            "LinkedIn vs cold email vs direct application, best time to apply, ATS bypass "
            "tips, and the optimal sequence of steps. Be tactical and specific (under 120 words). "
            "End with confidence score 0-100 'should apply'."
        ),
    },
    {
        "id": "risk_analyst",
        "name": "The Risk Analyst (Claude Haiku)",
        "provider": "anthropic",
        "system": (
            "You are a visa risk analyst for an Indian supply chain graduate applying for "
            "UK sponsorship jobs. Focus on: sponsorship risk (is the company a verified "
            "licensed sponsor?), wasted application risk, visa deadline risk, and what "
            "fallback options exist if this application fails. Under 120 words. "
            "End with confidence score 0-100 'should apply'."
        ),
    },
]

def _reddit_oracle_agent(job: dict, profile: dict, tier: str) -> Dict[str, Any]:
    """
    Rule-based 'Reddit Oracle' — encodes community wisdom directly into scored advice.
    No LLM needed. Patterns from r/SkilledWorkerVisaUK and r/IndiansInUK 2025-2026.
    """
    score = 50
    flags = []
    warnings = []

    # Tier check — most important
    if tier == "tier1":
        score += 30
        flags.append("✅ Tier 1 — GOV.UK verified + known active sponsor. Apply now.")
    elif tier == "tier2":
        score += 15
        flags.append("✅ Tier 2 — GOV.UK verified. Confirm recent CoS usage before applying.")
    else:
        score -= 30
        warnings.append("🔴 NOT on GOV.UK sponsor register. Very high risk. Verify before applying.")

    # Company size preference — mid-size / startup = less competition
    company = (job.get("company") or "").lower()
    big_corps = ["amazon", "google", "microsoft", "meta", "apple", "deloitte", "kpmg",
                 "mckinsey", "bcg", "goldman", "morgan stanley"]
    if any(b in company for b in big_corps):
        score -= 10
        warnings.append("⚠️  Major corp — very high competition from other visa seekers. Apply but also target SMEs.")
    else:
        score += 10
        flags.append("✅ Non-FAANG/Big4 — less competition from visa-seeking candidates.")

    # Salary threshold check
    salary_str = str(job.get("salary") or "")
    salary_nums = [int(s) for s in re.findall(r'\d{4,6}', salary_str)]
    if salary_nums:
        max_sal = max(salary_nums)
        if max_sal >= 41700:
            score += 10
            flags.append(f"✅ Salary £{max_sal:,} meets/exceeds £41,700 threshold.")
        elif max_sal >= 33000:
            score += 5
            flags.append(f"⚠️  Salary £{max_sal:,} — may qualify as New Entrant (£33k threshold).")
        else:
            score -= 20
            warnings.append(f"🔴 Salary £{max_sal:,} below £33k Skilled Worker minimum threshold.")

    # Psychometric test flag
    desc = (job.get("description") or "").lower()
    if any(t in desc for t in ["assessment", "psychometric", "numerical reasoning",
                                "verbal reasoning", "situational judgement", "aptitude"]):
        flags.append("📝 Psychometric test likely — prep with JobTestPrep/AssessmentDay BEFORE applying.")

    # Hiring window
    window = hiring_window_score()
    flags.append(f"📅 Current hiring window: {window['advice']}")
    if window['score'] < 40:
        score -= 10

    # ATS note
    flags.append(
        f"🤖 ATS tip: If asked 'require sponsorship?' answer: \""
        f"{ATS_BYPASS_LOGIC['smart_answer']}\""
    )

    confidence = max(0, min(100, score))
    return {
        "agent": "reddit_oracle",
        "name": "The Reddit Oracle (Rule-Based)",
        "opinion": " | ".join(flags + warnings),
        "warnings": warnings,
        "flags": flags,
        "confidence": confidence,
    }


def _call_llm_agent(agent: dict, job_context: str) -> Dict[str, Any]:
    """Call one LLM agent and return its opinion + confidence."""
    prompt = (
        f"{agent['system']}\n\n"
        f"JOB CONTEXT:\n{job_context}\n\n"
        f"Give your strategic assessment."
    )
    provider = agent["provider"]
    result = None
    if provider == "gemini":
        result = _gemini(prompt, max_tokens=200, temperature=0.6)
    elif provider == "huggingface":
        result = _huggingface(prompt, max_tokens=200)
    elif provider == "openai":
        result = _openai_llm(prompt, max_tokens=200)
    elif provider == "anthropic":
        result = _anthropic_llm(prompt, max_tokens=200)

    if not result:
        return {"agent": agent["id"], "name": agent["name"], "opinion": None, "confidence": None}

    # Extract confidence score from response
    confidence = None
    match = re.search(r'(?:confidence|score)[:\s]*([0-9]{1,3})', result, re.IGNORECASE)
    if match:
        try:
            confidence = int(match.group(1))
        except ValueError:
            pass

    return {
        "agent": agent["id"],
        "name": agent["name"],
        "opinion": result,
        "confidence": confidence,
    }


def run_multi_agent_debate(job: dict, profile: dict) -> Dict[str, Any]:
    """
    Run the full multi-agent debate for a single job.
    Returns a debate result with all agent opinions + synthesised action plan.
    """
    company  = job.get("company") or "Unknown"
    title    = job.get("title") or "Unknown role"
    spons    = job.get("sponsorship_status", "unknown")
    salary   = job.get("salary") or "not specified"
    desc     = (job.get("description") or "")[:300]
    location = job.get("location") or "UK"
    source   = job.get("source") or "unknown"

    tier = classify_company_tier(company, spons)
    window = hiring_window_score()

    job_context = (
        f"Role: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}\n"
        f"Salary: {salary}\n"
        f"Sponsorship status: {spons}\n"
        f"Company tier: {tier} — {COMPANY_TIER_LABELS.get(tier, '')}\n"
        f"Hiring window: {window['advice']}\n"
        f"Candidate: Indian supply chain graduate, PSW/Graduate Route visa holder\n"
        f"Candidate skills: {', '.join((profile.get('skills') or [])[:8])}\n"
        f"Experience: {profile.get('years_of_experience_hint') or 'graduate/junior'}\n"
        f"Job description excerpt: {desc}\n"
        f"Source: {source}"
    )

    # Run rule-based oracle first (always available)
    oracle_result = _reddit_oracle_agent(job, profile, tier)

    # Run LLM agents in parallel (only those with available API keys)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    llm_results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_call_llm_agent, agent, job_context): agent
            for agent in AGENT_PERSONAS
        }
        for fut in as_completed(futures):
            try:
                result = fut.result()
                if result.get("opinion"):   # only include agents that responded
                    llm_results.append(result)
            except Exception:
                pass

    all_opinions = [oracle_result] + llm_results

    # Compute consensus confidence
    valid_scores = [
        r["confidence"] for r in all_opinions
        if r.get("confidence") is not None
    ]
    consensus_confidence = (
        round(sum(valid_scores) / len(valid_scores)) if valid_scores else None
    )

    # Synthesis — ask best available LLM to read all opinions and produce action plan
    synthesis = _synthesise_debate(all_opinions, job_context, tier, window)

    return {
        "job_title":            title,
        "company":              company,
        "company_tier":         tier,
        "tier_label":           COMPANY_TIER_LABELS.get(tier, ""),
        "sponsorship_status":   spons,
        "hiring_window":        window,
        "agents":               all_opinions,
        "consensus_confidence": consensus_confidence,
        "synthesis":            synthesis,
        "ats_bypass":           ATS_BYPASS_LOGIC,
        "linkedin_outreach":    generate_linkedin_outreach(
                                    profile, "Hiring Manager", title, company),
        "followup_schedule":    generate_followup_schedule(datetime.utcnow().date()),
        "govuk_verified":       is_govuk_licensed_sponsor(company),
    }


def _synthesise_debate(opinions: List[Dict], job_context: str,
                        tier: str, window: dict) -> str:
    """Synthesis agent: reads all opinions, produces final action plan."""
    opinions_text = "\n\n".join(
        f"[{o['name']}] (confidence: {o.get('confidence', '?')}):\n{o.get('opinion', 'N/A')}"
        for o in opinions
    )
    synth_prompt = (
        f"You are synthesising a multi-agent debate about a UK visa sponsorship job application.\n\n"
        f"JOB CONTEXT:\n{job_context}\n\n"
        f"AGENT OPINIONS:\n{opinions_text}\n\n"
        f"Produce a final ACTION PLAN (under 200 words) with:\n"
        f"1. VERDICT: Apply / Apply with caution / Skip (and why in 1 sentence)\n"
        f"2. TOP 3 ACTIONS: Specific steps the candidate should take, in order\n"
        f"3. TIMING: When to apply based on hiring window\n"
        f"4. RISK LEVEL: Low / Medium / High and main risk factor\n"
        f"5. OVERALL CONFIDENCE: 0-100\n"
        f"Be direct and actionable. No filler."
    )
    return _llm(synth_prompt, max_tokens=400) or _offline_synthesis(opinions, tier, window)


def _offline_synthesis(opinions: List[Dict], tier: str, window: dict) -> str:
    """Rule-based synthesis fallback when no LLM is available."""
    valid_scores = [
        o["confidence"] for o in opinions if o.get("confidence") is not None
    ]
    avg = round(sum(valid_scores) / len(valid_scores)) if valid_scores else 50

    if tier == "tier3":
        verdict = "SKIP — company not on GOV.UK sponsor register. Do not waste application."
        risk = "HIGH — not a verified sponsor"
    elif avg >= 70:
        verdict = "APPLY — strong signals across agents."
        risk = "LOW" if tier == "tier1" else "MEDIUM"
    elif avg >= 50:
        verdict = "APPLY WITH CAUTION — verify sponsor status and salary threshold first."
        risk = "MEDIUM"
    else:
        verdict = "SKIP — low confidence. Redirect effort to better-matched roles."
        risk = "HIGH"

    actions = [
        "1. Verify company on GOV.UK sponsor register: https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers",
        "2. Tailor CV: 1 page, action + result bullets, mirror top 10 JD keywords",
        "3. Apply, then follow up every 5 days (3 times max)",
    ]
    if any("psychometric" in (o.get("opinion") or "").lower() for o in opinions) or \
       any("assessment" in (o.get("opinion") or "").lower() for o in opinions):
        actions.insert(1, "2. Prep psychometric tests: JobTestPrep or AssessmentDay BEFORE applying")

    return (
        f"VERDICT: {verdict}\n\n"
        f"TOP ACTIONS:\n" + "\n".join(actions) + "\n\n"
        f"TIMING: {window['advice']}\n\n"
        f"RISK LEVEL: {risk}\n\n"
        f"OVERALL CONFIDENCE: {avg}/100"
    )


# ---------------------------------------------------------------------------
# Batch strategy runner — enriches a list of jobs with debate results
# ---------------------------------------------------------------------------

def enrich_jobs_with_strategy(jobs: List[dict], profile: dict,
                               max_workers: int = 4) -> List[dict]:
    """
    Run multi-agent debate for each job and attach strategy results.
    Returns enriched job list sorted by consensus_confidence descending.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _enrich(job):
        try:
            strategy = run_multi_agent_debate(job, profile)
            job["strategy"] = strategy
            job["consensus_confidence"] = strategy.get("consensus_confidence") or 0
            job["company_tier"] = strategy.get("company_tier") or "tier3"
            job["govuk_verified"] = strategy.get("govuk_verified")
        except Exception:
            job["strategy"] = None
            job["consensus_confidence"] = 0
            job["company_tier"] = "tier3"
            job["govuk_verified"] = None
        return job

    results = []
    # Preload sponsor register once before threading
    if not _SPONSOR_CACHE_LOADED:
        _load_sponsor_register()

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_enrich, job): job for job in jobs}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception:
                pass

    results.sort(key=lambda x: x.get("consensus_confidence", 0), reverse=True)
    return results
