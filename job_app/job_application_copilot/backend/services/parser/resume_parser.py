"""
backend/services/parser/resume_parser.py
Extracts structured profile data from raw resume text or a PDF.
No external API required; uses keyword/regex heuristics.
"""
import re
from typing import List


SC_SKILLS = [
    "supply chain", "logistics", "procurement", "inventory", "operations",
    "demand planning", "forecasting", "sap", "erp", "excel", "power bi",
    "sql", "wms", "tms", "mrp", "s&op", "purchasing", "vendor management",
    "freight", "customs", "incoterms", "warehouse", "transport",
    "data analysis", "stakeholder management", "lean", "six sigma",
    "python", "tableau", "power query", "vlookup",
]


def parse_resume_text(text: str) -> dict:
    """
    Parameters
    ----------
    text : raw resume text (paste or extracted from PDF)

    Returns
    -------
    dict matching ResumeProfile schema
    """
    lower = text.lower()

    # Name: first non-empty line that is short and not a heading
    name = ""
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) < 60 and not any(
            h in line.lower() for h in ["curriculum", "resume", "profile", "summary"]
        ):
            name = line
            break

    # Email
    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    email  = emails[0] if emails else None

    # Phone
    phones = re.findall(r"(?:\+44|0)[\d\s\-()]{9,14}", text)
    phone  = phones[0].strip() if phones else None

    # LinkedIn
    linkedin = ""
    m = re.search(r"linkedin\.com/in/[\w\-]+", text, re.IGNORECASE)
    if m:
        linkedin = "https://" + m.group(0)

    # Skills
    found_skills = [s for s in SC_SKILLS if s in lower]

    # Years of experience hint
    exp_hint = ""
    m2 = re.search(r"(\d+)\+?\s+years?", text, re.IGNORECASE)
    if m2:
        exp_hint = m2.group(0)

    # Likely roles
    roles: List[str] = []
    role_kws = [
        "supply chain", "logistics", "procurement", "freight", "operations",
        "inventory", "warehouse", "customs", "shipping",
    ]
    for rk in role_kws:
        if rk in lower:
            roles.append(rk)

    return {
        "candidate_name":           name,
        "candidate_email":          email,
        "phone":                    phone,
        "linkedin_url":             linkedin,
        "skills":                   found_skills,
        "years_of_experience_hint": exp_hint,
        "likely_roles":             roles,
    }


def parse_resume_pdf(pdf_bytes: bytes) -> dict:
    """Extract text from PDF bytes (requires pypdf) then parse."""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return parse_resume_text(text)
    except ImportError:
        return {"note": "pypdf not installed — run: pip install pypdf"}
    except Exception as e:
        return {"note": f"PDF parse error: {e}"}
