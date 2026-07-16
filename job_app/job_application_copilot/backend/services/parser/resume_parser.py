"""
resume_parser.py — Smart resume text extractor and profile builder.

Extracts:
 - Candidate name, email, phone
 - Years of experience (from work history date ranges only, not education)
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
    r"customer (?:operations|service|support) (?:specialist|analyst|advisor|executive|manager)",
    r"operations specialist",
]

# ---------------------------------------------------------------------------
# Known CV section-header words — lines that are ONLY these words should
# never be treated as a candidate name.
# ---------------------------------------------------------------------------
_SECTION_HEADER_WORDS = {
    "profile", "summary", "objective", "overview",
    "skills", "core skills", "key skills", "technical skills",
    "experience", "work experience", "professional experience",
    "employment", "employment history", "work history",
    "education", "academic", "qualifications", "certifications",
    "achievements", "accomplishments", "awards",
    "references", "interests", "hobbies", "languages",
    "contact", "personal details", "personal information",
    "projects", "internship", "internships",
    "responsibilities", "key responsibilities",
    "career", "career history", "career objective",
    "training", "courses", "about", "about me",
}

# ---------------------------------------------------------------------------
# Degree patterns — anchored to avoid matching ordinary words that start
# with 'b' or 'm'. Each pattern must also pass the _is_valid_degree() check.
# ---------------------------------------------------------------------------
DEGREE_PATTERNS = [
    # B.Sc / BSc / B.Tech / BTech etc. — require word boundary + dot/slash after letter
    r"\bb\.(?:sc|eng|tech|com|a)\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbsc\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bb\.tech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbtech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbcom\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbba\.?\s*(?:in\s+)?[\w\s]{2,40}",
    # M.Sc / MSc / M.Tech / MTech etc.
    r"\bm\.(?:sc|ba|eng|tech|com|a)\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bmsc\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bm\.tech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bmtech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bmcom\.?\s*(?:in\s+)?[\w\s]{2,40}",
    # Full word forms — these were already safe but kept for completeness
    r"bachelor(?:'s)?\s+(?:of\s+)?[\w\s]{2,40}",
    r"master(?:'s)?\s+(?:of\s+)?[\w\s]{2,40}",
    r"\bmba\b",
    r"\bphd\b|\bph\.d\.?",
    r"\bpgdm\b",
    r"diploma\s+(?:in\s+)?[\w\s]{2,30}",
]

# Degree keywords that MUST appear in any matched string for it to be kept.
# Prevents accidental regex hits from being returned as education entries.
_DEGREE_KEYWORDS = {
    "bsc", "b.sc", "b.tech", "btech", "bcom", "bba",
    "msc", "m.sc", "m.tech", "mtech", "mcom",
    "bachelor", "master", "mba", "phd", "ph.d", "pgdm", "diploma",
}

# Section headers that signal start of EDUCATION — dates after these are NOT work experience.
# Extended with 'training', 'certifications', 'courses' which are common in Indian/UK CVs.
_EDUCATION_HEADERS = re.compile(
    r"^\s*(?:education|academic|qualification|university|college|school"
    r"|degree|study|studies|training|certifications?|courses?)",
    re.I | re.MULTILINE,
)

# Section headers that signal start of WORK EXPERIENCE.
# Extended with 'professional experience', 'work experience', 'key responsibilities',
# 'relevant experience', 'internship' — all common in Indian/UK CV formats.
_EXPERIENCE_HEADERS = re.compile(
    r"^\s*(?:experience|employment|work history|work experience"
    r"|professional experience|career|professional background"
    r"|positions?|roles?|key responsibilities|relevant experience|internship)",
    re.I | re.MULTILINE,
)

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
    """
    Return the candidate's full name from the top of the CV.

    Guards added (fixes 'CORE SKILLS' bug):
    1. Skip lines whose stripped, lowercased value is in _SECTION_HEADER_WORDS.
    2. Skip all-caps single-word / two-word lines (section headers are almost
       always ALL CAPS in many CV templates, but real names are Title Case).
    3. The line must contain at least one space (i.e. first + last name) OR be
       a single word of ≥ 4 chars that is Title-cased (not all-caps).
    4. Skip lines that are purely numeric or contain digits run together.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 60:
            continue
        # Skip lines with URLs / email addresses
        if re.search(r"[@|http|www|linkedin|github]", line, re.I):
            continue
        # Skip known header keywords
        if re.search(
            r"(?:resume|curriculum|vitae|address|phone|email|mobile|tel"
            r"|linkedin|github|profile|summary|objective|skills|education"
            r"|experience|employment|work|career|references|contact|about)",
            line, re.I,
        ):
            continue
        # Skip if the whole line (normalised) is a known section header
        if line.strip().lower() in _SECTION_HEADER_WORDS:
            continue
        # Skip pure numbers / lines with leading digits (dates, phone numbers)
        if re.match(r"^[\d\s\-\+\(\)]+$", line):
            continue
        words = line.split()
        # Skip single-word ALL-CAPS lines (section headers like 'PROFILE', 'SKILLS')
        if len(words) <= 2 and line == line.upper() and any(c.isalpha() for c in line):
            continue
        # Must look like a name: either ≥2 words, or a single Title-Cased word ≥4 chars
        if len(words) >= 2:
            return line
        if len(words) == 1 and len(line) >= 4 and line[0].isupper() and not line.isupper():
            return line
    return None


def _is_valid_degree(match: str) -> bool:
    """Return True only if the matched string contains a recognisable degree keyword."""
    ml = match.lower()
    return any(kw in ml for kw in _DEGREE_KEYWORDS)


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
    """
    Extract degree / qualification strings.

    Fix: all single-letter abbreviation patterns (b.sc, m.tech etc.) are now
    anchored with \\b and require the abbreviation form (not just 'b' + any letter).
    Every match is also validated through _is_valid_degree() to reject accidental
    hits on words like 'Based', 'Business', 'Between', etc.
    """
    tl = text.lower()
    found = []
    for pattern in DEGREE_PATTERNS:
        for m in re.finditer(pattern, tl):
            deg = m.group(0).strip().title()
            if len(deg) > 3 and _is_valid_degree(deg) and deg not in found:
                found.append(deg)
    return found[:3]


def _get_work_section_only(text: str) -> str:
    """
    Returns only the portion(s) of the CV text that are under a
    work/experience section header, stopping at the next education
    section header.  Falls back to full text if no headers found.
    """
    exp_matches = [(m.start(), "work") for m in _EXPERIENCE_HEADERS.finditer(text)]
    edu_matches = [(m.start(), "edu")  for m in _EDUCATION_HEADERS.finditer(text)]
    all_sections = sorted(exp_matches + edu_matches, key=lambda x: x[0])

    if not exp_matches:
        if not edu_matches:
            return text
        edu_start = min(p for p, _ in edu_matches)
        return text[:edu_start]

    work_chunks = []
    for i, (pos, kind) in enumerate(all_sections):
        if kind != "work":
            continue
        next_pos = all_sections[i + 1][0] if i + 1 < len(all_sections) else len(text)
        work_chunks.append(text[pos:next_pos])

    return "\n".join(work_chunks) if work_chunks else text


def _extract_years_experience(text: str) -> Optional[str]:
    """
    Calculate total years of WORK experience.
    Strategy:
    1. Look for explicit statement: '3 years of experience'
    2. Extract date ranges ONLY from the work/experience section
    3. Merge overlapping ranges to avoid double-counting
    4. Fallback: count distinct work years from work section only
    """
    # --- Step 1: explicit statement ---
    explicit = re.search(
        r"(\d+)\+?\s*years?\s+(?:of\s+)?(?:work\s+)?(?:professional\s+)?experience",
        text, re.I
    )
    if explicit:
        yrs = int(explicit.group(1))
        return f"{yrs}+ years" if yrs >= 1 else "Graduate / Fresher"

    # --- Step 2: work section date ranges only ---
    work_text = _get_work_section_only(text)

    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
    }
    now = datetime.utcnow()

    date_range_pattern = re.compile(
        r"(?:(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
        r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"[\s,]*)?\s*(\d{4})\s*[-\u2013\u2014to]+\s*"
        r"(?:(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
        r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)?"
        r"[\s,]*\s*(\d{4}|present|current|now|date|till date|to date))",
        re.I,
    )

    intervals = []
    for m in date_range_pattern.finditer(work_text):
        start_month_str, start_year, end_month_str, end_year_str = m.groups()
        try:
            sy = int(start_year)
            sm = month_map.get((start_month_str or "").lower()[:3], 1)
            if re.search(r"present|current|now|date", str(end_year_str), re.I):
                ey, em = now.year, now.month
            else:
                ey = int(end_year_str)
                em = month_map.get((end_month_str or "").lower()[:3], 12)
            if sy > ey or sy < 1990 or ey > now.year + 1:
                continue
            start_idx = sy * 12 + sm
            end_idx   = ey * 12 + em
            if end_idx > start_idx:
                intervals.append((start_idx, end_idx))
        except (ValueError, TypeError):
            continue

    if intervals:
        intervals.sort()
        merged = [list(intervals[0])]
        for s, e in intervals[1:]:
            if s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        total_months = sum(e - s for s, e in merged)
        years = total_months // 12
        months_rem = total_months % 12
        if years == 0:
            return f"{months_rem} months"
        if years == 1:
            return f"~1 year {months_rem}mo"
        return f"~{years} years"

    # --- Step 3: fallback --- distinct work years in work section ---
    work_years = set(re.findall(r"\b(20[0-9]{2})\b", work_text))
    if len(work_years) >= 3:
        return "2-4 years (estimated)"
    if len(work_years) >= 1:
        return "1-2 years (estimated)"

    return "Graduate / Fresher"


# ---------------------------------------------------------------------------
# Main profile builder
# ---------------------------------------------------------------------------

def build_profile_preview(filename: str, text: str) -> Dict[str, Any]:
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
