"""
tests/test_scraper.py  —  smoke tests for scraper helpers
Run with:  pytest tests/ -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.services.jobs.scraper import make_job, score_job, is_likely_sponsor


def test_make_job_basic():
    j = make_job("Supply Chain Analyst", "DHL", "London", "£30k", "SAP logistics", "https://example.com", "Test")
    assert j is not None
    assert j["title"] == "Supply Chain Analyst"
    assert j["company"] == "DHL"


def test_make_job_empty_title():
    j = make_job("", "DHL", "London", "", "", "", "Test")
    assert j is None


def test_make_job_strips_nan():
    j = make_job("Analyst", "nan", "London", "none", "", "", "Test")
    assert j["company"] == ""
    assert j["salary"] == ""


def test_score_job_supply_chain():
    j = {"title": "Supply Chain Analyst", "description": "SAP, logistics, procurement, demand planning"}
    score = score_job(j)
    assert score >= 20


def test_score_job_director_penalty():
    j = {"title": "Director of Supply Chain", "description": "supply chain logistics"}
    score = score_job(j)
    assert score < score_job({"title": "Supply Chain Analyst", "description": "supply chain logistics"})


def test_score_job_visa_bonus():
    j = {"title": "Logistics Coordinator", "description": "visa sponsorship available skilled worker",
         "source": "Tier2Jobs (Visa)"}
    score = score_job(j, visa_bonus=True)
    assert score >= 20


def test_is_likely_sponsor_dhl():
    assert is_likely_sponsor("DHL") is True


def test_is_likely_sponsor_unknown():
    assert is_likely_sponsor("Random Local Bakery") is False
