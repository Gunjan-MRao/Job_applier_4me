import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from docx import Document
from pypdf import PdfReader


COMMON_SKILLS = [
    # Data & Analytics
    "python", "sql", "r", "excel", "power bi", "tableau", "looker", "qlik",
    "data analysis", "data science", "data visualisation", "data visualization",
    "machine learning", "deep learning", "nlp", "statistics", "spss", "sas",
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "jupyter",
    # Supply Chain & Logistics
    "supply chain", "logistics", "procurement", "sourcing", "purchasing",
    "inventory management", "demand planning", "forecasting", "s&op",
    "warehouse management", "3pl", "freight", "import/export", "customs",
    "order management", "supplier management", "vendor management",
    "lean", "six sigma", "kaizen", "continuous improvement",
    "transport planning", "last mile", "cold chain", "reverse logistics",
    # ERP & Tools
    "sap", "erp", "oracle", "sap mm", "sap sd", "sap ewm",
    "netsuite", "dynamics 365", "jde", "manhattan", "blue yonder",
    "cplex", "siemens nx", "minitab", "autocad",
    # Operations & Project
    "operations", "operations management", "project management",
    "stakeholder management", "change management", "process improvement",
    "business analysis", "requirements gathering", "agile", "scrum", "prince2",
    "risk management", "budget management", "cost reduction", "kpi",
    # Engineering
    "mechanical engineering", "industrial engineering", "manufacturing",
    "quality assurance", "quality control", "iso", "lean manufacturing",
    "production planning", "capacity planning", "maintenance",
    # Cloud & Tech
    "aws", "azure", "gcp", "docker", "kubernetes", "git",
    "java", "javascript", "typescript", "react", "node", "api",
    "power automate", "power apps", "vba", "ms office",
    # Finance & Commercial
    "financial analysis", "budgeting", "forecasting", "p&l",
    "cost analysis", "pricing", "commercial", "contract management",
    # Soft skills (searchable)
    "communication", "team leadership", "cross-functional", "problem solving",
    "analytical", "presentation", "negotiation",
]

ROLE_HINTS = [
    # Supply Chain & Logistics
    "supply chain analyst", "supply chain manager", "supply chain coordinator",
    "supply chain graduate", "supply chain consultant",
    "logistics coordinator", "logistics analyst", "logistics manager",
    "procurement analyst", "procurement manager", "procurement specialist",
    "demand planner", "demand planning analyst",
    "inventory analyst", "inventory manager",
    "operations analyst", "operations manager", "operations coordinator",
    "warehouse manager", "distribution manager",
    "transport planner", "transport coordinator",
    "sourcing analyst", "sourcing manager",
    # Data & Analytics
    "data analyst", "data scientist", "business intelligence analyst",
    "reporting analyst", "insights analyst", "analytics manager",
    "machine learning engineer",
    # Business & Commercial
    "business analyst", "management consultant", "strategy analyst",
    "commercial analyst", "financial analyst",
    "customer operations specialist", "customer success manager",
    # Engineering & Manufacturing
    "process engineer", "industrial engineer", "manufacturing engineer",
    "quality engineer", "continuous improvement engineer",
    "production planner", "planning engineer",
    # Tech
    "software engineer", "backend developer", "frontend developer",
    "full stack developer", "product manager", "project manager",
    # Graduate / Entry level catch-all
    "graduate scheme", "graduate trainee", "graduate analyst",
    "junior analyst", "junior engineer", "junior manager",
    "associate analyst", "entry level",
]

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def extract_text_from_pdf(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def extract_text_from_docx(file_path: Path) -> str:
    doc = Document(str(file_path))
    return "\n".join(p.text for p in doc.paragraphs).strip()


def extract_resume_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(file_path)
    if suffix == ".docx":
        return extract_text_from_docx(file_path)
    raise ValueError(f"Unsupported file type: {suffix}")


def extract_email(text: str) -> Optional[str]:
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return m.group(0) if m else None


def extract_phone(text: str) -> Optional[str]:
    m = re.search(r"(\+?\d[\d\-\s\(\)]{8,}\d)", text)
    return m.group(0).strip() if m else None


def extract_candidate_name(text: str) -> Optional[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:8]:
        if len(line.split()) in (2, 3, 4, 5) and "@" not in line and len(line) < 60:
            if re.search(r"[A-Za-z]", line):
                return line.title()
    return None


def extract_skills(text: str) -> list[str]:
    text_lower = text.lower()
    found = [skill for skill in COMMON_SKILLS if skill in text_lower]
    return sorted(set(found))


def extract_role_hints(text: str) -> list[str]:
    text_lower = text.lower()
    found = [role for role in ROLE_HINTS if role in text_lower]
    return sorted(set(found))


def _normalize_text(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r", "\n"))


def _find_section(text: str, start_headers: list[str], end_headers: list[str]) -> str:
    norm = _normalize_text(text)
    lower = norm.lower()
    start_idx = -1
    for header in start_headers:
        idx = lower.find(header.lower())
        if idx != -1:
            start_idx = idx
            break
    if start_idx == -1:
        return norm
    end_idx = len(norm)
    for header in end_headers:
        idx = lower.find(header.lower(), start_idx + 1)
        if idx != -1:
            end_idx = min(end_idx, idx)
    return norm[start_idx:end_idx].strip()


def _extract_explicit_experience_phrase(text: str) -> Optional[str]:
    patterns = [
        r"(\d+)\+?\s+years?\s+of\s+(?:progressive\s+)?experience",
        r"experience\s+spanning\s+(\d+)\+?\s+years?",
        r"over\s+(\d+)\+?\s+years?\s+of\s+experience",
    ]
    lower = text.lower()
    for pattern in patterns:
        m = re.search(pattern, lower)
        if m:
            return f"{m.group(1)}+ years"
    return None


def _parse_month_year(token: str):
    token = token.strip().lower().replace("\u2013", "-").replace("\u2014", "-")
    if token in {"present", "current", "now"}:
        today = datetime.today()
        return today.year, today.month, True
    m = re.match(r"([A-Za-z]{3,9})\s+(\d{4})", token)
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        year = int(m.group(2))
        if month:
            return year, month, False
    m = re.match(r"(\d{4})", token)
    if m:
        return int(m.group(1)), 1, False
    return None


def _extract_date_ranges_from_experience_section(text: str):
    exp_section = _find_section(
        text,
        start_headers=["professional experience", "experience", "work experience", "employment history"],
        end_headers=["education", "additional information", "certifications", "projects", "skills", "core skills"]
    )
    exp_section = exp_section.replace("\u2013", "-").replace("\u2014", "-")
    pattern = re.compile(
        r"(?P<start>(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+\d{4}|\d{4})\s*-\s*(?P<end>(?:Present|Current|Now|(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+\d{4}|\d{4}))",
        flags=re.IGNORECASE
    )
    ranges = []
    for m in pattern.finditer(exp_section):
        start_parsed = _parse_month_year(m.group("start"))
        end_parsed = _parse_month_year(m.group("end"))
        if start_parsed and end_parsed:
            sy, sm, _ = start_parsed
            ey, em, _ = end_parsed
            if (ey, em) >= (sy, sm):
                ranges.append(((sy, sm), (ey, em)))
    return ranges


def _merge_ranges(ranges):
    if not ranges:
        return []
    ranges = sorted(ranges, key=lambda x: x[0])
    merged = [ranges[0]]
    for current in ranges[1:]:
        (csy, csm), (cey, cem) = current
        (msy, msm), (mey, mem) = merged[-1]
        if csy * 12 + csm <= mey * 12 + mem + 1:
            if (cey, cem) > (mey, mem):
                merged[-1] = ((msy, msm), (cey, cem))
        else:
            merged.append(current)
    return merged


def _sum_range_months(ranges):
    total = 0
    for (sy, sm), (ey, em) in ranges:
        total += max((ey - sy) * 12 + (em - sm + 1), 0)
    return total


def estimate_experience_hint(text: str) -> Optional[str]:
    explicit = _extract_explicit_experience_phrase(text)
    if explicit:
        return explicit
    ranges = _extract_date_ranges_from_experience_section(text)
    if not ranges:
        return None
    merged = _merge_ranges(ranges)
    total_months = _sum_range_months(merged)
    if total_months <= 0:
        return None
    years = total_months // 12
    months = total_months % 12
    if years > 0 and months > 0:
        return f"{years} years {months} months"
    if years > 0:
        return f"{years}+ years"
    return f"{months} months"


def build_profile_preview(filename: str, text: str) -> dict:
    cleaned = " ".join(text.split())
    return {
        "filename": filename,
        "candidate_name": extract_candidate_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "skills": extract_skills(text),
        "likely_roles": extract_role_hints(text),
        "years_of_experience_hint": estimate_experience_hint(text),
        "preview": cleaned[:800],
    }
