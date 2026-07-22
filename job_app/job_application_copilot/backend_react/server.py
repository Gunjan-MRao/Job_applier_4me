"""
Job Application Copilot — React backend (port 8001)
MongoDB-backed FastAPI server that serves the /api/* routes
consumed by the Emergent React frontend.

This file is a copy of Job_app_Emergent/backend/server.py, adapted to:
  - read MONGO_URL / DB_NAME / EMERGENT_LLM_KEY from .env
  - use pdfplumber instead of PyMuPDF (already in requirements)
  - be launched by launch.py when RUN_MODE=react

The existing Streamlit app (port 8000 / 8501) is completely unaffected.
"""
import os
import re
import io
import csv
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "jobcopilot")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")
DEPARTURE_DATE = os.environ.get("DEPARTURE_DATE", "2027-01-06")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="Job Application Copilot — React API")
api = APIRouter(prefix="/api")

REG_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

SUFFIXES = {"ltd", "limited", "plc", "llp", "llc", "inc", "uk", "group", "holdings",
            "the", "company", "co", "services", "solutions", "international"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalise(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    tokens = [t for t in n.split() if t and t not in SUFFIXES]
    return " ".join(tokens).strip()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Profile(BaseModel):
    id: str = "primary"
    candidate_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    target_roles: List[str] = []
    skills: List[str] = []
    years_experience: str = ""
    summary: str = ""
    cv_text: str = ""
    updated_at: str = Field(default_factory=now_iso)


class JobIn(BaseModel):
    title: str
    company: str
    location: str = "United Kingdom"
    url: str = ""
    salary: str = ""
    description: str = ""
    source: str = "manual"
    remote: bool = False
    track: str = "uk_sponsored"


class StatusUpdate(BaseModel):
    status: str


class DiscoverIn(BaseModel):
    query: str = ""
    location: str = "United Kingdom"


class CountryDiscover(BaseModel):
    country: str


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------
async def llm_json(system: str, prompt: str) -> Optional[dict]:
    if not EMERGENT_LLM_KEY:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=str(uuid.uuid4()),
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-6")
        resp = await chat.send_message(UserMessage(text=prompt))
        text = resp if isinstance(resp, str) else str(resp)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        print("LLM error:", e)
    return None


# ---------------------------------------------------------------------------
# Sponsor register
# ---------------------------------------------------------------------------
def _find_csv_url() -> Optional[str]:
    try:
        r = requests.get(REG_PAGE, headers=UA, timeout=25)
        links = re.findall(r"https://[^\"\s]+\.csv", r.text)
        return sorted(set(links))[-1] if links else None
    except Exception as e:
        print("csv url error:", e)
        return None


async def _load_sponsors() -> dict:
    url = _find_csv_url()
    if not url:
        return {"ok": False, "error": "Could not locate the GOV.UK register CSV."}
    r = requests.get(url, headers=UA, timeout=90)
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig", errors="replace"))))
    header, data = rows[0], rows[1:]
    docs = []
    for row in data:
        if len(row) < 5:
            continue
        name = (row[0] or "").strip()
        if not name:
            continue
        docs.append({
            "name": name,
            "norm": normalise(name),
            "city": (row[1] or "").strip(),
            "county": (row[2] or "").strip(),
            "rating": (row[3] or "").strip(),
            "route": (row[4] or "").strip(),
        })
    await db.sponsors.drop()
    if docs:
        for i in range(0, len(docs), 5000):
            await db.sponsors.insert_many(docs[i:i + 5000])
        await db.sponsors.create_index("norm")
    await db.meta.update_one(
        {"_id": "sponsors"},
        {"$set": {"count": len(docs), "source_url": url, "loaded_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True, "count": len(docs), "loaded_at": now_iso()}


async def verify_sponsor(company: str) -> dict:
    norm = normalise(company)
    if not norm:
        return {"is_licensed_sponsor": False, "match": None}
    doc = await db.sponsors.find_one({"norm": norm})
    if not doc:
        first = norm.split()[0] if norm.split() else ""
        if len(first) >= 4:
            doc = await db.sponsors.find_one({"norm": {"$regex": f"^{re.escape(first)}( |$)"}})
    if doc:
        return {
            "is_licensed_sponsor": True,
            "match": {"name": doc["name"], "city": doc["city"],
                      "rating": doc["rating"], "route": doc["route"]},
        }
    return {"is_licensed_sponsor": False, "match": None}


# ---------------------------------------------------------------------------
# Fit scoring
# ---------------------------------------------------------------------------
SENIOR = ["senior", "lead", "head of", "director", "principal", "chief", "vp ", "manager"]


def fit_score(job: dict, profile: dict) -> dict:
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    combined = f"{title} {desc}"
    roles = [r.lower() for r in (profile.get("target_roles") or []) if r.strip()]
    skills = [s.lower() for s in (profile.get("skills") or []) if s.strip()]
    role_hits = sum(1 for r in roles if r and r in combined)
    role_score = min(int(role_hits / max(len(roles), 1) * 50), 50) if roles else 25
    skill_hits = sum(1 for s in skills if s and s in combined)
    skill_score = min(skill_hits * 5, 35)
    spons_bonus = 15 if job.get("is_licensed_sponsor") else 0
    exp = profile.get("years_experience") or ""
    has_exp = any(c.isdigit() for c in exp) and not exp.strip().startswith("0")
    senior_pen = -20 if any(t in title for t in SENIOR) and not has_exp else 0
    score = max(0, min(role_score + skill_score + spons_bonus + senior_pen, 100))
    level = "strong" if score >= 60 else ("moderate" if score >= 35 else "weak")
    return {"fit_score": score, "fit_level": level}


def classify_keywords(desc: str) -> str:
    t = (desc or "").lower()
    neg = ["no sponsorship", "unable to sponsor", "cannot sponsor", "no visa sponsorship",
           "must already have the right to work", "will not sponsor", "no tier 2"]
    pos = ["visa sponsorship", "sponsorship available", "skilled worker", "certificate of sponsorship",
           "tier 2", "we can sponsor", "sponsorship may be available"]
    if any(x in t for x in neg):
        return "no"
    if any(x in t for x in pos):
        return "yes"
    return "unknown"


async def generate_documents(job: dict, profile: dict) -> dict:
    name = profile.get("candidate_name") or "the candidate"
    company = job.get("company", "the company")
    title = job.get("title", "the role")
    licensed = job.get("is_licensed_sponsor")
    spons = job.get("sponsorship_status", "unknown")
    if spons == "no":
        spons_rule = "Do NOT mention visa sponsorship."
    elif licensed or spons == "yes":
        spons_rule = (f"In the FINAL paragraph, add 1-2 confident sentences noting the candidate requires a "
                      f"Certificate of Sponsorship (Skilled Worker route) and has confirmed {company} holds a "
                      f"sponsor licence, and is ready to support the compliance process.")
    else:
        spons_rule = (f"In the FINAL paragraph, add 1-2 sentences noting the candidate requires a Certificate of "
                      f"Sponsorship (Skilled Worker route) and would welcome discussing whether {company} can support this.")
    system = ("You are an expert UK career coach who writes warm, specific, non-generic application materials "
              "for candidates seeking visa-sponsored roles. You always return strict JSON.")
    prompt = (
        f"Candidate: {name}. Experience: {profile.get('years_experience','')}. "
        f"Skills: {', '.join(profile.get('skills') or [])}. "
        f"Target roles: {', '.join(profile.get('target_roles') or [])}. "
        f"Profile summary: {profile.get('summary','')}. "
        f"CV extract: {(profile.get('cv_text') or '')[:1500]}.\n\n"
        f"Job: '{title}' at {company} ({job.get('location','UK')}). "
        f"Job description: {(job.get('description') or '')[:1200]}.\n\n"
        f"Write application materials tailored to THIS job. {spons_rule}\n"
        "Return strict JSON with keys: "
        "\"cover_letter\" (string, under 240 words), "
        "\"cv_summary\" (string, 3-4 line professional summary), "
        "\"recruiter_message\" (string, 60-90 word LinkedIn/email message), "
        "\"why_fit\" (array of 3 short bullet strings), "
        "\"tailoring_tips\" (array of 2-3 short bullet strings)."
    )
    data = await llm_json(system, prompt)
    if not data:
        cl = (f"Dear Hiring Team at {company},\n\nThe {title} role is exactly the kind of position "
              f"I have been working towards. My background in "
              f"{', '.join((profile.get('target_roles') or ['this field'])[:2])} "
              f"and skills in {', '.join((profile.get('skills') or ['relevant tools'])[:3])} "
              f"align closely with what you need. I would welcome a brief call this week.\n\n"
              + ("" if spons == "no" else
                 "One practical note: I would require a Certificate of Sponsorship under the Skilled Worker route.\n\n")
              + f"Kind regards,\n{name}")
        return {
            "cover_letter": cl,
            "cv_summary": profile.get("summary", "") or "Experienced professional seeking UK opportunities.",
            "recruiter_message": (f"Hi, I came across the {title} role at {company} — strong match for my background. "
                                   + ("" if spons == "no" else " Note: I would need a Certificate of Sponsorship.")),
            "why_fit": ["Relevant target role", "Matching skills", "Motivated candidate"],
            "tailoring_tips": ["Mirror the job's keywords", "Lead with your strongest achievement"],
            "generated_by": "template",
        }
    data["generated_by"] = "ai"
    return data


# ---------------------------------------------------------------------------
# CV parsing
# ---------------------------------------------------------------------------
def extract_text(filename: str, content: bytes) -> str:
    fn = filename.lower()
    if fn.endswith(".pdf"):
        import pdfplumber
        text = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text.append(page.extract_text() or "")
        return "\n".join(text)
    if fn.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(content))
        return "\n".join(p.text for p in d.paragraphs)
    return content.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@api.get("/")
async def root():
    return {"status": "ok", "app": "Job Application Copilot — React API"}


@api.get("/config")
async def config():
    return {"departure_date": DEPARTURE_DATE}


@api.get("/profile")
async def get_profile():
    doc = await db.profiles.find_one({"id": "primary"}, {"_id": 0})
    return doc or Profile().model_dump()


@api.post("/profile")
async def save_profile(profile: Profile):
    profile.id = "primary"
    profile.updated_at = now_iso()
    await db.profiles.update_one({"id": "primary"}, {"$set": profile.model_dump()}, upsert=True)
    return profile.model_dump()


@api.post("/profile/parse-cv")
async def parse_cv(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text = extract_text(file.filename, content)
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {e}")
    if not text.strip():
        raise HTTPException(400, "No text could be extracted from the CV.")
    system = "You extract structured candidate data from a CV. Always return strict JSON."
    prompt = (
        f"Extract from this CV. Return strict JSON with keys: candidate_name (string), email (string), "
        f"phone (string), location (string), years_experience (string e.g. '3 years'), "
        f"skills (array of strings, max 15), target_roles (array of 3-5 likely job titles), "
        f"summary (a 2-3 sentence professional summary).\n\nCV:\n{text[:6000]}"
    )
    data = await llm_json(system, prompt) or {}
    existing = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    merged = {
        "id": "primary",
        "candidate_name": data.get("candidate_name") or existing.get("candidate_name", ""),
        "email": data.get("email") or existing.get("email", ""),
        "phone": data.get("phone") or existing.get("phone", ""),
        "location": data.get("location") or existing.get("location", ""),
        "years_experience": data.get("years_experience") or existing.get("years_experience", ""),
        "skills": data.get("skills") or existing.get("skills", []),
        "target_roles": data.get("target_roles") or existing.get("target_roles", []),
        "summary": data.get("summary") or existing.get("summary", ""),
        "cv_text": text[:12000],
        "updated_at": now_iso(),
    }
    await db.profiles.update_one({"id": "primary"}, {"$set": merged}, upsert=True)
    return {"parsed": bool(data), "profile": merged}


@api.get("/sponsors/status")
async def sponsors_status():
    meta = await db.meta.find_one({"_id": "sponsors"}, {"_id": 0})
    return meta or {"count": 0, "loaded_at": None}


@api.post("/sponsors/refresh")
async def sponsors_refresh():
    return await _load_sponsors()


@api.get("/sponsors/search")
async def sponsors_search(q: str):
    result = await verify_sponsor(q)
    others = []
    if not result["is_licensed_sponsor"] and len(normalise(q)) >= 3:
        first = normalise(q).split()[0]
        cur = db.sponsors.find({"norm": {"$regex": re.escape(first)}}, {"_id": 0}).limit(8)
        others = [d async for d in cur]
    return {"query": q, **result, "suggestions": others}


async def _enrich_meta(job_in: JobIn, profile: dict) -> dict:
    job = job_in.model_dump()
    verified = await verify_sponsor(job["company"])
    job.update(verified)
    kw = classify_keywords(job["description"])
    if kw == "no":
        job["sponsorship_status"] = "no"
    elif verified["is_licensed_sponsor"] or kw == "yes":
        job["sponsorship_status"] = "yes"
    else:
        job["sponsorship_status"] = "unknown"
    job.update(fit_score(job, profile))
    job["id"] = str(uuid.uuid4())
    job["status"] = "saved"
    job["created_at"] = now_iso()
    for k in ("cover_letter", "cv_summary", "recruiter_message"):
        job.setdefault(k, None)
    return job


async def _enrich_and_store(job_in: JobIn) -> dict:
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    job = await _enrich_meta(job_in, profile)
    job.update(await generate_documents(job, profile))
    await db.jobs.insert_one(dict(job))
    job.pop("_id", None)
    return job


@api.post("/jobs")
async def add_job(job_in: JobIn):
    return await _enrich_and_store(job_in)


@api.get("/jobs")
async def list_jobs(status: Optional[str] = None, track: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    if track:
        q["track"] = track
    cur = db.jobs.find(q, {"_id": 0}).sort("fit_score", -1)
    return [j async for j in cur]


@api.get("/jobs/stats")
async def job_stats():
    jobs = [j async for j in db.jobs.find({}, {"_id": 0, "status": 1, "is_licensed_sponsor": 1, "track": 1})]
    by_status = {}
    for j in jobs:
        by_status[j.get("status", "saved")] = by_status.get(j.get("status", "saved"), 0) + 1
    uk = [j for j in jobs if j.get("track", "uk_sponsored") == "uk_sponsored"]
    return {
        "total": len(jobs), "uk_sponsored": len(uk), "remote_intl": len(jobs) - len(uk),
        "sponsors": sum(1 for j in jobs if j.get("is_licensed_sponsor")),
        "by_status": by_status,
    }


@api.patch("/jobs/{job_id}")
async def update_job(job_id: str, upd: StatusUpdate):
    res = await db.jobs.update_one({"id": job_id}, {"$set": {"status": upd.status}})
    if res.matched_count == 0:
        raise HTTPException(404, "Job not found")
    return await db.jobs.find_one({"id": job_id}, {"_id": 0})


@api.post("/jobs/{job_id}/regenerate")
async def regenerate(job_id: str):
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    docs = await generate_documents(job, profile)
    await db.jobs.update_one({"id": job_id}, {"$set": docs})
    return await db.jobs.find_one({"id": job_id}, {"_id": 0})


@api.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    await db.jobs.delete_one({"id": job_id})
    return {"ok": True}


@api.post("/jobs/discover")
async def discover(body: DiscoverIn):
    import asyncio
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    query = body.query or " ".join((profile.get("target_roles") or ["graduate analyst"])[:1])
    jobs, breakdown = await asyncio.to_thread(sources.gather, query, body.location or "United Kingdom")
    seen, unique = set(), []
    for j in jobs:
        key = ((j.get("title") or "").lower().strip(), (j.get("company") or "").lower().strip())
        if key in seen:
            continue
        seen.add(key)
        unique.append(j)
    created = {"uk_sponsored": 0, "remote_intl": 0}
    for item in unique:
        exists = await db.jobs.find_one({"title": item["title"], "company": item["company"]})
        if exists:
            continue
        job_in = JobIn(**{k: item[k] for k in ("title", "company", "location", "url",
                                               "salary", "description", "source", "remote", "track")})
        job = await _enrich_meta(job_in, profile)
        await db.jobs.insert_one(dict(job))
        created[item.get("track", "uk_sponsored")] += 1
    total = created["uk_sponsored"] + created["remote_intl"]
    return {"ok": True, "created": total, "created_by_track": created, "breakdown": breakdown,
            "message": f"Added {created['uk_sponsored']} UK-sponsored + {created['remote_intl']} remote/international roles."}


@api.post("/jobs/generate-all")
async def generate_all(track: Optional[str] = None, force: bool = False):
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    q = {}
    if track:
        q["track"] = track
    if not force:
        q["$or"] = [{"cover_letter": None}, {"cover_letter": {"$exists": False}}]
    jobs = [j async for j in db.jobs.find(q, {"_id": 0})]
    count = 0
    for job in jobs:
        docs = await generate_documents(job, profile)
        await db.jobs.update_one({"id": job["id"]}, {"$set": docs})
        count += 1
    return {"ok": True, "generated": count}


@api.get("/jobs/{job_id}/export")
async def export_job(job_id: str, format: str = "pdf"):
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    safe = re.sub(r"[^a-zA-Z0-9]+", "_",
                  f"{job.get('company','')}_{job.get('title','')}").strip("_")[:60]
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    buf = io.BytesIO()
    doc_rl = SimpleDocTemplate(buf, pagesize=A4, topMargin=22*mm, bottomMargin=20*mm,
                               leftMargin=22*mm, rightMargin=22*mm)
    ss = getSampleStyleSheet()
    name_style = ParagraphStyle("name", parent=ss["Title"], fontSize=20,
                                textColor=HexColor("#7c2d12"), spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontSize=9,
                         textColor=HexColor("#78716c"), spaceAfter=14)
    head = ParagraphStyle("head", parent=ss["Heading2"], fontSize=12,
                          textColor=HexColor("#c2410c"), spaceBefore=10, spaceAfter=6)
    body_style = ParagraphStyle("body", parent=ss["Normal"], fontSize=10.5, leading=15, spaceAfter=6)
    story = []
    cand_name = profile.get("candidate_name") or "Candidate"
    story.append(Paragraph(cand_name, name_style))
    contact = " &nbsp;·&nbsp; ".join(
        [x for x in [profile.get("email"), profile.get("phone"), profile.get("location")] if x])
    if contact:
        story.append(Paragraph(contact, sub))
    story.append(Paragraph(f"Cover Letter — {job.get('title','')} at {job.get('company','')}", head))
    for para in (job.get("cover_letter") or "").split("\n"):
        if para.strip():
            story.append(Paragraph(para.replace("&", "&amp;"), body_style))
        else:
            story.append(Spacer(1, 6))
    story.append(Paragraph("Tailored CV Summary", head))
    story.append(Paragraph((job.get("cv_summary") or "").replace("&", "&amp;"), body_style))
    doc_rl.build(story)
    data = buf.getvalue()
    fn = f"{safe}.pdf"
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={fn}"})


@api.get("/jobs/{job_id}/recruiter-email")
async def recruiter_email(job_id: str):
    import asyncio
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    company = job.get("company", "")
    RECRUITER_PREFIXES = ["careers", "recruitment", "hr", "talent", "jobs", "hiring", "hello", "info"]
    def _domains_for(co):
        try:
            r = requests.get("https://autocomplete.clearbit.com/v1/companies/suggest",
                             params={"query": co}, timeout=10)
            return [x.get("domain") for x in r.json() if x.get("domain")][:3]
        except Exception:
            return []
    def _hunter_emails(domain):
        key = os.environ.get("HUNTER_API_KEY")
        if not key:
            return []
        try:
            r = requests.get("https://api.hunter.io/v2/domain-search",
                             params={"domain": domain, "api_key": key, "limit": 10}, timeout=15)
            return [{"email": e.get("value"), "type": "verified",
                     "role": e.get("position") or "",
                     "confidence": e.get("confidence")}
                    for e in r.json().get("data", {}).get("emails", [])]
        except Exception:
            return []
    domains = await asyncio.to_thread(_domains_for, company)
    verified = []
    for d in domains[:1]:
        verified += await asyncio.to_thread(_hunter_emails, d)
    guesses, seen = [], set()
    for d in domains[:2]:
        for p in RECRUITER_PREFIXES:
            g = {"email": f"{p}@{d}", "type": "guess", "role": p}
            if g["email"] not in seen:
                seen.add(g["email"])
                guesses.append(g)
    result = {"company": company, "domains": domains, "verified": verified,
              "guesses": guesses[:12], "hunter_enabled": bool(os.environ.get("HUNTER_API_KEY"))}
    await db.jobs.update_one({"id": job_id},
                             {"$set": {"recruiter_domains": domains,
                                       "recruiter_guesses": [g["email"] for g in guesses[:12]]}})
    return result


class SendEmail(BaseModel):
    recipient_email: str = ""
    to_self: bool = False
    attach_pdf: bool = True


@api.post("/jobs/{job_id}/send-email")
async def send_email(job_id: str, body: SendEmail):
    import asyncio, base64
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return {"ok": False, "needs_key": True,
                "message": "Add RESEND_API_KEY to .env to enable sending."}
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    if not job.get("recruiter_message"):
        raise HTTPException(400, "Generate documents first.")
    recipient = (profile.get("email") or "").strip() if body.to_self else body.recipient_email.strip()
    if not recipient or "@" not in recipient:
        raise HTTPException(400, "Valid recipient email required.")
    import resend
    resend.api_key = api_key
    cand_name = profile.get("candidate_name") or "Candidate"
    params = {
        "from": os.environ.get("SENDER_EMAIL", "onboarding@resend.dev"),
        "to": [recipient],
        "subject": f"{job.get('title','Role')} — {cand_name}",
        "html": "<div style=\"font-family:Arial,sans-serif\">" + job["recruiter_message"].replace("\n", "<br>") + "</div>",
    }
    try:
        res = await asyncio.to_thread(resend.Emails.send, params)
    except Exception as e:
        raise HTTPException(500, f"Failed to send: {e}")
    await db.jobs.update_one(
        {"id": job_id},
        {"$set": {"email_sent_to": recipient, "email_sent_at": now_iso(),
                  "status": "applied" if job.get("status") == "saved" else job.get("status")}}
    )
    return {"ok": True, "sent_to": recipient}


@api.post("/jobs/discover-country")
async def discover_country(body: CountryDiscover):
    import asyncio
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    query = (profile.get("target_roles") or ["supply chain logistics"])[0]
    supported, jobs = await asyncio.to_thread(sources.adzuna_country, query, body.country)
    if not supported:
        return {"ok": False, "unsupported": True,
                "message": f"Live search not available for {body.country} yet."}
    created = 0
    for item in jobs:
        exists = await db.jobs.find_one({"title": item["title"], "company": item["company"]})
        if exists:
            continue
        job_in = JobIn(**{k: item[k] for k in ("title", "company", "location", "url",
                                               "salary", "description", "source", "remote", "track")})
        job = await _enrich_meta(job_in, profile)
        job["country"] = body.country
        await db.jobs.insert_one(dict(job))
        created += 1
    return {"ok": True, "created": created, "country": body.country}


@api.get("/sponsorship-countries")
async def sponsorship_countries(refresh: bool = False):
    if not refresh:
        cached = await db.meta.find_one({"_id": "countries"}, {"_id": 0})
        if cached and cached.get("countries"):
            return cached
    profile = await db.profiles.find_one({"id": "primary"}, {"_id": 0}) or {}
    roles = ", ".join(profile.get("target_roles") or ["Supply Chain Analyst"])
    exp = profile.get("years_experience") or "early-career"
    system = "You are an expert global immigration and careers advisor. Always return strict JSON."
    prompt = (
        f"A candidate with {exp} experience targeting: {roles}. "
        "List 8 countries that actively sponsor skilled-worker visas for logistics/supply-chain. "
        "Return strict JSON: {\"countries\": [{\"country\": string, \"flag\": emoji, "
        "\"visa_route\": string, \"demand\": \"High\"|\"Medium\", "
        "\"difficulty\": \"Easy\"|\"Moderate\"|\"Hard\", "
        "\"relevance\": string, \"notes\": string, \"job_boards\": [string]}]}."
    )
    data = await llm_json(system, prompt) or {"countries": []}
    payload = {"countries": data.get("countries", []), "generated_at": now_iso()}
    await db.meta.update_one({"_id": "countries"}, {"$set": payload}, upsert=True)
    return payload


# ---------------------------------------------------------------------------
# Serve React build (if present)
# ---------------------------------------------------------------------------
_FRONTEND_BUILD = Path(__file__).resolve().parents[1] / "frontend" / "build"
if _FRONTEND_BUILD.exists():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND_BUILD / "static")), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_react(full_path: str = ""):
        from fastapi.responses import FileResponse
        index = _FRONTEND_BUILD / "index.html"
        return FileResponse(str(index))


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await db.jobs.create_index("id")
    await db.profiles.create_index("id")
    await db.jobs.update_many({"track": {"$exists": False}}, {"$set": {"track": "uk_sponsored"}})
