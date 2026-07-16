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
# Known CV section-header words — lines that consist ONLY of these words
# should never be treated as a candidate name.
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

# Hard-skip keywords: if the ENTIRE line matches one of these as a
# substring it is definitely not a name.  NOTE: deliberately narrow —
# do NOT put short common words like 'work', 'career' here because they
# would kill innocent name lines.  Only put things that are structurally
# impossible in a human name.
_HARD_SKIP_RE = re.compile(
    r"(?:resume|curriculum vitae|\bcv\b|address:|phone:|mobile:|tel:|email:"
    r"|linkedin\.com|github\.com|http|www\.|@"
    r"|years? of experience|supply chain|logistics|procurement"
    r"|\bskills\b|\beducation\b|\bsummary\b|\bprofile\b|\bobjective\b"
    r"|\bexperience\b|\bemployment\b|\bqualification)",
    re.I,
)

# Degree patterns — anchored to avoid matching ordinary words starting with 'b'/'m'.
# Each pattern must also pass _is_valid_degree().
DEGREE_PATTERNS = [
    r"\bb\.(?:sc|eng|tech|com|a)\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbsc\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bb\.tech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbtech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbcom\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bbba\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bm\.(?:sc|ba|eng|tech|com|a)\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bmsc\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bm\.tech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bmtech\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"\bmcom\.?\s*(?:in\s+)?[\w\s]{2,40}",
    r"bachelor(?:'s)?\s+(?:of\s+)?[\w\s]{2,40}",
    r"master(?:'s)?\s+(?:of\s+)?[\w\s]{2,40}",
    r"\bmba\b",
    r"\bphd\b|\bph\.d\.?",
    r"\bpgdm\b",
    r"diploma\s+(?:in\s+)?[\w\s]{2,30}",
]

_DEGREE_KEYWORDS = {
    "bsc", "b.sc", "b.tech", "btech", "bcom", "bba",
    "msc", "m.sc", "m.tech", "mtech", "mcom",
    "bachelor", "master", "mba", "phd", "ph.d", "pgdm", "diploma",
}

_EDUCATION_HEADERS = re.compile(
    r"^\s*(?:education|academic|qualification|university|college|school"
    r"|degree|study|studies|training|certifications?|courses?)",
    re.I | re.MULTILINE,
)

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


def _score_name_line(line: str, email_line_idx: int, line_idx: int) -> int:
    """
    Score a line for likelihood of being the candidate name.
    Returns -1 if the line should be hard-skipped entirely.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return -1

    # Hard skip: contains structural CV keywords or email/URL
    if _HARD_SKIP_RE.search(stripped):
        return -1

    # Hard skip: purely numeric / date-looking / phone-looking
    if re.match(r"^[\d\s\-\+\(\)/|,\.]+$", stripped):
        return -1

    # Hard skip: line IS a known section header (exact match after lower)
    if stripped.lower() in _SECTION_HEADER_WORDS:
        return -1

    # Hard skip: single token that is all-caps AND <=3 chars (abbreviation/initial)
    tokens = stripped.split()
    if len(tokens) == 1 and stripped.isupper() and len(stripped) <= 3:
        return -1

    # Hard skip: contains a pipe/bar separator common in headers ("Name | Location | Phone")
    # but allow names with hyphens
    if "|" in stripped or stripped.count(",") > 1:
        return -1

    score = 0

    # Count purely-alphabetic tokens (letters only, including single initials)
    alpha_tokens = [t for t in tokens if re.match(r"^[A-Za-z\.]+$", t)]
    if len(alpha_tokens) < 1:
        return -1  # no alphabetic content at all

    if len(alpha_tokens) >= 2:
        score += 10  # looks like first + last (or first + initial + last)
    if len(alpha_tokens) >= 3:
        score += 3   # three-part name (common in Indian names: Bindu K P)

    # All tokens are alpha-only (no digits mixed in)
    if all(re.match(r"^[A-Za-z\.]+$", t) for t in tokens):
        score += 5

    # Proximity to email line: names are almost always within 5 lines of email
    if email_line_idx >= 0:
        dist = abs(line_idx - email_line_idx)
        if dist <= 2:
            score += 10
        elif dist <= 5:
            score += 6
        elif dist <= 10:
            score += 2

    # Appears in first 5 lines of the document — strong signal
    if line_idx <= 4:
        score += 8
    elif line_idx <= 10:
        score += 4

    # Looks like a job title — penalise
    if re.search(
        r"(?:analyst|manager|coordinator|specialist|executive|officer"
        r"|director|consultant|advisor|associate|intern|engineer|developer)",
        stripped, re.I,
    ):
        score -= 8

    # Penalise if it contains digits (likely a date, address, or phone fragment)
    if re.search(r"\d", stripped):
        score -= 10

    return score


def _extract_name(text: str, filename: str = "") -> Optional[str]:
    """
    Extract the candidate's full name from the top of the CV.

    Strategy:
    1. Collect the first 25 non-empty lines from the document.
    2. Find which line index contains the email address.
    3. Score every candidate line via _score_name_line().
    4. Return the highest-scoring line that scores >= 8.
    5. Fallback: derive from filename (e.g. 'Bindu_resume.pdf' → 'Bindu').
    """
    all_lines = [l.rstrip() for l in text.splitlines()]

    # Find the email line index (search full text, get its line position)
    email_line_idx = -1
    email_pat = re.compile(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", re.I)
    for i, line in enumerate(all_lines[:40]):
        if email_pat.search(line):
            email_line_idx = i
            break

    # Score the first 25 non-empty lines
    best_score = 7   # minimum threshold
    best_line: Optional[str] = None
    checked = 0
    for i, raw_line in enumerate(all_lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        checked += 1
        if checked > 25:
            break
        s = _score_name_line(stripped, email_line_idx, i)
        if s > best_score:
            best_score = s
            best_line = stripped

    if best_line:
        # Normalise: Title-case if all-caps (e.g. 'BINDU K P' → 'Bindu K P')
        if best_line == best_line.upper():
            best_line = best_line.title()
        return best_line

    # Fallback: extract from filename
    stem = Path(filename).stem if filename else ""
    # Remove common suffixes: '_resume', '_cv', '_2024', '-resume' etc.
    stem = re.sub(r"[_\-]?(resume|cv|updated|new|final|\d{4})", "", stem, flags=re.I)
    stem = stem.replace("_", " ").replace("-", " ").strip()
    if stem and len(stem) >= 3:
        return stem.title()

    return None


def _is_valid_degree(match: str) -> bool:
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
    tl = text.lower()
    found = []
    for pattern in DEGREE_PATTERNS:
        for m in re.finditer(pattern, tl):
            deg = m.group(0).strip().title()
            if len(deg) > 3 and _is_valid_degree(deg) and deg not in found:
                found.append(deg)
    return found[:3]


def _get_work_section_only(text: str) -> str:
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
    explicit = re.search(
        r"(\d+)\+?\s*years?\s+(?:of\s+)?(?:work\s+)?(?:professional\s+)?experience",
        text, re.I
    )
    if explicit:
        yrs = int(explicit.group(1))
        return f"{yrs}+ years" if yrs >= 1 else "Graduate / Fresher"

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
        "candidate_name":            _extract_name(text, filename),
        "email":                     _extract_email(text),
        "phone":                     _extract_phone(text),
        "skills":                    _extract_skills(text),
        "likely_roles":              _extract_roles(text),
        "education":                 _extract_education(text),
        "years_of_experience_hint":  _extract_years_experience(text),
        "preview":                   " ".join(text.split())[:600],
    }
