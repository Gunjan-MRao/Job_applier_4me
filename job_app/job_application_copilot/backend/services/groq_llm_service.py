"""
groq_llm_service.py  — Zero-cost LLM scoring via Groq (free tier)

Replaces all paid OpenAI / Anthropic calls with Groq's free API.
Model: llama-3.3-70b-versatile  (128k context, fast, free tier)

Free-tier limits (as of 2025):
  - 30 requests / minute
  - 6 000 tokens / minute
  - 500 000 tokens / day

Usage:
    from backend.services.groq_llm_service import score_job_with_llm, generate_cover_letter

Requires:
    pip install groq
    GROQ_API_KEY=<your key>  in .env  (get free key at console.groq.com)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy client — only initialised when first called so the app doesn't crash
# if groq is not installed or GROQ_API_KEY is missing.
# ---------------------------------------------------------------------------
_client = None

MODEL = "llama-3.3-70b-versatile"
_RETRY_WAIT = 5   # seconds to wait on rate-limit before retrying once


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from groq import Groq  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "groq package not installed.  Run: pip install groq"
        )
    key = os.environ.get("GROQ_API_KEY") or _read_env_file()
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY not set.  Add it to your .env file.\n"
            "Get a free key at: https://console.groq.com"
        )
    _client = Groq(api_key=key)
    return _client


def _read_env_file() -> str:
    """Read GROQ_API_KEY from .env next to this file or two levels up."""
    from pathlib import Path
    for candidate in (
        Path(__file__).parent / ".env",
        Path(__file__).parent.parent.parent / ".env",
    ):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("GROQ_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return ""


def _chat(messages: list[dict], max_tokens: int = 1024, retries: int = 1) -> str:
    """Call Groq chat completions with one automatic retry on rate-limit."""
    client = _get_client()
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            err = str(exc).lower()
            if "rate" in err and attempt < retries:
                logger.warning("Groq rate limit hit — waiting %ss", _RETRY_WAIT)
                time.sleep(_RETRY_WAIT)
            else:
                raise
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_job_with_llm(job: dict, profile: dict) -> dict:
    """
    Ask Groq's LLaMA to score a job against a resume profile.

    Returns a dict:
    {
        "fit_score":           int   0-100,
        "sponsor_confidence":  int   0-100  (likelihood company sponsors visas),
        "recommendation":      str   "APPLY" | "SKIP" | "INVESTIGATE",
        "key_matches":         list[str],
        "missing_skills":      list[str],
        "reasoning":           str,
    }
    Falls back to a local keyword score on any error.
    """
    title       = job.get("title", "Unknown role")
    company     = job.get("company", "Unknown company")
    description = (job.get("description") or "")[:3000]   # cap tokens
    salary      = job.get("salary") or "not stated"
    sponsor_txt = job.get("sponsorship_status") or "unknown"

    resume_summary = _build_resume_summary(profile)

    prompt = f"""You are a UK job application expert specialising in Skilled Worker Visa sponsorship.

CANDIDATE PROFILE:
{resume_summary}

JOB POSTING:
Title:    {title}
Company:  {company}
Salary:   {salary}
Sponsorship mentioned: {sponsor_txt}
Description (first 3000 chars):
{description}

Task: Analyse this job for the candidate and return ONLY valid JSON with this exact schema:
{{
  "fit_score": <integer 0-100>,
  "sponsor_confidence": <integer 0-100, how likely this company sponsors Skilled Worker visas>,
  "recommendation": "APPLY" | "SKIP" | "INVESTIGATE",
  "key_matches": [<up to 5 skills/experiences that match>],
  "missing_skills": [<up to 5 important gaps>],
  "reasoning": "<one concise sentence>"
}}

Rules:
- fit_score >= 70  AND sponsor_confidence >= 60 → recommendation = "APPLY"
- fit_score < 40   OR  sponsor_confidence < 30  → recommendation = "SKIP"
- Otherwise                                     → recommendation = "INVESTIGATE"
- If description contains "no sponsorship", "only UK citizens", or "SC cleared" → fit_score=0, recommendation="SKIP"

Return ONLY the JSON object, no markdown fences, no extra text."""

    try:
        raw = _chat([{"role": "user", "content": prompt}], max_tokens=512)
        return _parse_json_response(raw)
    except Exception as exc:
        logger.warning("Groq LLM score failed (%s) — falling back to keyword score", exc)
        return _fallback_score(job, profile)


def generate_cover_letter(job: dict, profile: dict) -> str:
    """
    Generate a tailored cover letter using Groq LLaMA.
    Returns the cover letter as a plain-text string.
    """
    title        = job.get("title", "the advertised role")
    company      = job.get("company", "your company")
    description  = (job.get("description") or "")[:2000]
    name         = profile.get("candidate_name") or "the candidate"
    skills       = ", ".join((profile.get("skills") or [])[:8])
    roles        = ", ".join((profile.get("likely_roles") or [])[:3])
    experience   = profile.get("years_of_experience_hint") or "graduate-level"

    prompt = f"""Write a professional, concise UK cover letter (max 3 paragraphs, 250 words) for:

Candidate: {name}
Experience level: {experience}
Key skills: {skills}
Target roles: {roles}

Applying to: {title} at {company}
Job description excerpt: {description}

Requirements:
- UK English spelling
- Mention Skilled Worker Visa sponsorship politely in the final paragraph
- Do NOT use hollow phrases like "I am writing to express my interest"
- Open with a specific achievement or strong value statement
- Address the letter "Dear Hiring Team"
- Close with "Yours sincerely, {name}"

Return only the letter text, no subject line."""

    try:
        return _chat([{"role": "user", "content": prompt}], max_tokens=600)
    except Exception as exc:
        logger.warning("Groq cover letter failed (%s) — using offline template", exc)
        return _fallback_cover_letter(job, profile)


def generate_cold_email(job: dict, profile: dict, hr_name: str = "") -> str:
    """
    Generate a short cold recruiter email.
    """
    title   = job.get("title", "a relevant role")
    company = job.get("company", "your organisation")
    name    = profile.get("candidate_name") or "the candidate"
    skills  = ", ".join((profile.get("skills") or [])[:5])
    greeting = f"Dear {hr_name}" if hr_name else "Dear Hiring Team"

    prompt = f"""Write a cold recruiter email (max 150 words) from {name} applying for {title} at {company}.
Candidate skills: {skills}
Greeting: {greeting}
Requirements:
- UK English
- Mention availability to discuss Skilled Worker Visa sponsorship
- Professional but warm tone
- End with a clear call-to-action (request a brief call)
- Close "Kind regards, {name}"
Return only the email body, no subject line."""

    try:
        return _chat([{"role": "user", "content": prompt}], max_tokens=350)
    except Exception as exc:
        logger.warning("Groq cold email failed (%s) — using offline template", exc)
        return f"{greeting},\n\nI am reaching out regarding opportunities at {company}...\n\nKind regards,\n{name}"


def extract_hr_contact(about_page_text: str, company: str) -> dict:
    """
    Given a company's 'About Us' page text, extract HR contact details.

    Returns:
    {
        "hr_name":     str | None,
        "email_guess": str | None,
        "confidence":  int 0-100,
    }
    """
    text = about_page_text[:3000]
    prompt = f"""Analyse this company 'About Us' page text for {company} and extract HR/recruitment contact information.

Text:
{text}

Return ONLY valid JSON:
{{
  "hr_name": "<full name of HR manager or recruiter, or null>",
  "email_guess": "<inferred email address e.g. john.smith@company.com, or null>",
  "email_format": "<pattern used e.g. firstname.lastname@domain.com, or null>",
  "confidence": <integer 0-100>
}}"""

    try:
        raw = _chat([{"role": "user", "content": prompt}], max_tokens=256)
        return _parse_json_response(raw)
    except Exception:
        return {"hr_name": None, "email_guess": None, "email_format": None, "confidence": 0}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_resume_summary(profile: dict) -> str:
    name     = profile.get("candidate_name") or "Candidate"
    skills   = ", ".join((profile.get("skills") or [])[:12]) or "not specified"
    roles    = ", ".join((profile.get("likely_roles") or [])[:5]) or "not specified"
    edu      = ", ".join((profile.get("education") or [])[:3]) or "not specified"
    exp      = profile.get("years_of_experience_hint") or "not specified"
    preview  = (profile.get("preview") or "")[:600]
    return (
        f"Name: {name}\n"
        f"Experience: {exp}\n"
        f"Target roles: {roles}\n"
        f"Skills: {skills}\n"
        f"Education: {edu}\n"
        f"Resume excerpt: {preview}"
    )


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from LLM response, tolerating markdown fences."""
    # Strip ```json ... ``` fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`")
    # Find first { ... } block
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(cleaned)


def _fallback_score(job: dict, profile: dict) -> dict:
    """Local keyword-overlap score used when Groq is unavailable."""
    from backend.services.job_fit_service import score_job  # noqa: PLC0415
    score = score_job(job, profile)
    return {
        "fit_score":          score,
        "sponsor_confidence": 50,
        "recommendation":     "APPLY" if score >= 70 else "INVESTIGATE" if score >= 40 else "SKIP",
        "key_matches":        [],
        "missing_skills":     [],
        "reasoning":          "Groq unavailable — local keyword score used.",
    }


def _fallback_cover_letter(job: dict, profile: dict) -> str:
    name    = profile.get("candidate_name") or "the candidate"
    title   = job.get("title", "the advertised role")
    company = job.get("company", "your company")
    skills  = ", ".join((profile.get("skills") or [])[:5]) or "relevant skills"
    return (
        f"Dear Hiring Team,\n\n"
        f"I am a motivated professional with expertise in {skills}, applying for the "
        f"{title} position at {company}. My background equips me well to contribute "
        f"immediately to your team.\n\n"
        f"I would welcome the opportunity to discuss how I can add value, and I am "
        f"open to discussing Skilled Worker Visa sponsorship if required.\n\n"
        f"Yours sincerely,\n{name}"
    )
