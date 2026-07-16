"""
tests/test_scoring.py  —  tests for automation_runtime fit scorer
Run with:  pytest tests/ -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.services.automation_runtime import ai_fit_score, classify_sponsorship


def test_fit_score_supply_chain_title():
    job = {"title": "Supply Chain Analyst", "description": ""}
    result = ai_fit_score(job, None, ["supply chain", "logistics"])
    assert result["fit_score"] >= 10, "SC title must always score >= 10 (title_floor)"


def test_fit_score_short_desc_uses_title():
    job = {"title": "Logistics Coordinator", "description": "Apply now"}
    result = ai_fit_score(job, None, ["logistics"])
    assert result["fit_score"] >= 10


def test_fit_score_senior_penalty():
    job_senior = {"title": "Head of Supply Chain",  "description": "supply chain logistics sap"}
    job_junior = {"title": "Supply Chain Analyst",  "description": "supply chain logistics sap"}
    s_senior = ai_fit_score(job_senior, None, ["supply chain"])["fit_score"]
    s_junior = ai_fit_score(job_junior, None, ["supply chain"])["fit_score"]
    assert s_senior < s_junior


def test_classify_sponsorship_positive():
    assert classify_sponsorship("Visa sponsorship available, skilled worker visa") == "yes"


def test_classify_sponsorship_negative():
    assert classify_sponsorship("No sponsorship, must have right to work in UK") == "no"


def test_classify_sponsorship_unknown():
    assert classify_sponsorship("Competitive salary and great team") == "unknown"
