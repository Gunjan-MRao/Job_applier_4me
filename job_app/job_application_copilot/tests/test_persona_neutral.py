"""
test_persona_neutral.py — Proof the pipeline is persona-neutral.

The original concern: keywords/scoring might be driven by a hardcoded persona
(e.g. "Bindu" / supply-chain constants) rather than the actual parsed resume.

These tests run the parser and scorer with a DIFFERENT resume (a backend
software engineer, not the supply-chain fixture) and assert that the extracted
skills/roles and the fit scores reflect THAT resume's real content — a
supply-chain job must NOT out-score a software job for a software candidate.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from backend.services.parser.resume_parser import build_profile_preview
from backend.pipeline import scoring

SWE_FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume_swe.txt"
SC_FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume.txt"


@pytest.fixture()
def swe_profile():
    text = SWE_FIXTURE.read_text(encoding="utf-8")
    return build_profile_preview("Aarav_Mehta_Resume.txt", text)


@pytest.fixture()
def sc_profile():
    text = SC_FIXTURE.read_text(encoding="utf-8")
    return build_profile_preview("Bindu_Sharma_Resume.txt", text)


def test_parser_reflects_software_resume(swe_profile):
    """The parser must extract software skills from a software CV, not persona."""
    skills = set(swe_profile["skills"])
    assert "python" in skills
    assert "docker" in skills
    assert {"react", "aws", "django", "fastapi"} & skills
    # It must NOT invent supply-chain skills that aren't in this resume.
    assert "supply chain" not in skills
    assert "sap" not in skills
    # A software role should be recognised.
    roles = " ".join(swe_profile["likely_roles"]).lower()
    assert "software engineer" in roles or "backend" in roles


SWE_JOB = {
    "title": "Backend Software Engineer",
    "company": "CloudScale",
    "description": (
        "Build REST APIs and microservices in Python and Django. Deploy with "
        "Docker and Kubernetes on AWS. Strong Git and CI/CD experience required."
    ),
    "location": "United Kingdom",
}

SC_JOB = {
    "title": "Supply Chain Analyst",
    "company": "DHL",
    "description": (
        "Support demand planning, procurement and inventory management. SAP and "
        "advanced Excel essential. Experience with S&OP and forecasting."
    ),
    "location": "United Kingdom",
}


def test_software_candidate_prefers_software_job(swe_profile):
    """A software candidate must score a software job above a supply-chain job."""
    keywords = ["backend software engineer", "python developer"]
    swe_score = scoring.score_job(SWE_JOB, swe_profile, keywords)["fit_score"]
    sc_score = scoring.score_job(SC_JOB, swe_profile, keywords)["fit_score"]
    assert swe_score > sc_score, (
        f"software job ({swe_score}) should beat supply-chain job ({sc_score}) "
        "for a software candidate"
    )


def test_supply_chain_candidate_prefers_supply_chain_job(sc_profile):
    """Mirror check: the supply-chain candidate must prefer the supply-chain job.

    Same scorer, opposite resume -> opposite winner. This proves the ranking is
    driven by the resume, not a baked-in persona.
    """
    keywords = ["supply chain analyst", "logistics coordinator"]
    sc_score = scoring.score_job(SC_JOB, sc_profile, keywords)["fit_score"]
    swe_score = scoring.score_job(SWE_JOB, sc_profile, keywords)["fit_score"]
    assert sc_score > swe_score, (
        f"supply-chain job ({sc_score}) should beat software job ({swe_score}) "
        "for a supply-chain candidate"
    )
