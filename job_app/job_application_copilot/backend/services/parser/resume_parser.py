"""
resume_parser.py — Smart resume text extractor and profile builder.

Extracts:
 - Candidate name, email, phone
 - Years of experience (from date ranges in work history)
 - Likely roles (job titles found in text)
 - Skills (keyword matching)
 - Education (degree + university)
 - Preview text
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Skills keyword bank
# ---------------------------------------------------------------------------
SKILLS_BANK = [
    "supply chain", "logistics", "procurement", "sap", "excel", "operations",
    "forecasting", "power bi", "inventory management", "demand planning", "erp",
    "sql", "python", "tableau", "s&op", "vendor management", "warehouse",
    "transport", "purchasing", "category management", "ariba", "oracle",
    "six sigma", "lean", "project management", "stakeholder management",
    "data analysis", "cost reduction", "continuous improvement", "3pl",
    "customs", "import", "export", "freight", "distribution", "planning",
    "budgeting", "kpi", "reporting", "microsoft office", "visio",
    "negotiation", "contract management", "risk management",
]

# Common supply chain / operations job titles
ROLE_PATTERNS = [
    r"supply chain (?:analyst|manager|coordinator|specialist|executive|lead|officer|consultant)",
    r"logistics (?:analyst|manager|coordinator|specialist|executive|lead|officer)",
    r"procurement (?:analyst|manager|coordinator|specialist|executive|lead|officer|advisor)",
    r"demand plan(?:ner|ning (?:analyst|manager|specialist))",
    r"inventory (?:analyst|manager|coordinator|planner|specialist)",
    r"operations (?:analyst|manager|coordinator|specialist|executive|lead)",
    r"transport(?:ation)? (?:analyst|manager|coordinator|planner|specialist)",
    r"warehouse (?:manager|coordinator|supervisor|operative|analyst)",
    r"purchasing (?:manager|analyst|officer|coordinator|specialist)",
    r"category (?:manager|analyst|specialist|buyer)",
    r"s(?:&|and)op (?:analyst|manager|planner|specialist)",
    r"business analyst",
    r"data analyst",
    r"project (?:manager|coordinator|analyst)",
    r"graduate (?:analyst|trainee|scheme|programme)",
    r"junior (?:analyst|manager|coordinator|executive)",
    r"senior (?:analyst|manager|coordinator|executive|specialist)",
]

# Degree keywords
DEGREE_PATTERNS = [
    r"b\.?(?:sc|eng|tech|com|a)\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"m\.?(?:sc|ba|eng|tech|com|a)\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"bachelor(?:'s)?\s+(?:of\s+)?[\w\s]{2,40}",
    r"master(?:'s)?\s+(?:of\s+)?[\w\s]{2,40}",
    r"mba",
    r"phd|ph\.d",
    r"pgdm",
    r"diploma\s+(?:in\s+)?[\w\s]{2,30}",
]

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_resume_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".docx":
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        pass
    return ""

# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

def _extract_email(text: str) -> Optional[str]:
    m = re.search(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", text, re.I)
    return m.group(0) if m else None

def _extract_phone(text: str) -> Optional[str]:
    m = re.search(r"(?:\+?\d[\s\-\(\)]{0,2}){9,13}", text)
    return m.group(0).strip() if m else None

def _extract_name(text: str) -> Optional[str]:
    """First non-empty line is usually the name on a CV."""
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) < 60 and not re.search(r"[@|http|www]", line, re.I):
            # Skip lines that look like section headers or addresses
            if not re.search(r"(?:resume|curriculum|vitae|address|phone|email|linkedin)", line, re.I):
                return line
    return None

def _extract_skills(text: str) -> List[str]:
    tl = text.lower()
    return [s for s in SKILLS_BANK if s in tl]

def _extract_roles(text: str) -> List[str]:
    tl = text.lower()
    found = []
    for pattern in ROLE_PATTERNS:
        matches = re.findall(pattern, tl)
        for m in matches:
            role = m.strip().title()
            if role not in found:
                found.append(role)
    return found[:6]

def _extract_education(text: str) -> List[str]:
    tl = text.lower()
    found = []
    for pattern in DEGREE_PATTERNS:
        matches = re.findall(pattern, tl)
        for m in matches:
            deg = m.strip().title()
            if len(deg) > 3 and deg not in found:
                found.append(deg)
    return found[:3]

def _extract_years_experience(text: str) -> Optional[str]:
    """
    Attempts to calculate total years of experience by finding date ranges
    like 'Jan 2020 – Mar 2023', '2019 - 2022', 'June 2021 to Present', etc.
    Falls back to looking for explicit statements like '3 years of experience'.
    """
    # Explicit statement: '3 years of experience' / '3+ years'
    explicit = re.search(
        r"(\d+)\+?\s*years?\s+(?:of\s+)?(?:work\s+)?experience",
        text, re.I
    )
    if explicit:
        yrs = int(explicit.group(1))
        return f"{yrs}+ years" if yrs >= 1 else "Graduate / Fresher"

    # Date range extraction
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
    }
    now = datetime.utcnow()

    # Pattern: Month YYYY – Month YYYY  or  YYYY – YYYY  or  Month YYYY to Present
    date_range_pattern = re.compile(
        r"(?:(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"[\s,]*)?\s*(\d{4})\s*[-–—to]+\s*"
        r"(?:(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)?"
        r"[\s,]*\s*(\d{4}|present|current|now|date|till date|to date))",
        re.I,
    )

    total_months = 0
    seen_ranges = set()
    for m in date_range_pattern.finditer(text):
        start_month_str, start_year, end_month_str, end_year_str = m.groups()
        try:
            sy = int(start_year)
            sm = month_map.get((start_month_str or "").lower()[:3], 1)
            if re.search(r"present|current|now|date", str(end_year_str), re.I):
                ey, em = now.year, now.month
            else:
                ey = int(end_year_str)
                em = month_map.get((end_month_str or "").lower()[:3], 12)
            # Skip if start > end or dates look like years not experience (e.g., university years)
            if sy > ey or sy < 1990 or ey > now.year + 1:
                continue
            key = (sy, sm, ey, em)
            if key in seen_ranges:
                continue
            seen_ranges.add(key)
            months = (ey - sy) * 12 + (em - sm)
            if 0 < months < 600:  # sanity check
                total_months += months
        except (ValueError, TypeError):
            continue

    if total_months > 0:
        years = total_months // 12
        months_rem = total_months % 12
        if years == 0:
            return f"{months_rem} months"
        if years < 2:
            return f"~{years} year{'s' if years > 1 else ''} {months_rem}mo"
        return f"~{years} years"

    # Fallback: count number of job entries (sections with years)
    job_year_hits = re.findall(r"\b(20[0-9]{2})\b", text)
    unique_years = len(set(job_year_hits))
    if unique_years >= 4:
        return "2–4 years (estimated)"
    if unique_years >= 2:
        return "1–2 years (estimated)"

    return "Graduate / Fresher"

# ---------------------------------------------------------------------------
# Main profile builder
# ---------------------------------------------------------------------------

def build_profile_preview(filename: str, text: str) -> Dict[str, Any]:
    """Build a structured profile dict from raw resume text."""
    return {
        "filename":                  filename,
        "candidate_name":            _extract_name(text),
        "email":                     _extract_email(text),
        "phone":                     _extract_phone(text),
        "skills":                    _extract_skills(text),
        "likely_roles":              _extract_roles(text),
        "education":                 _extract_education(text),
        "years_of_experience_hint":  _extract_years_experience(text),
        "preview":                   " ".join(text.split())[:600],
    }
