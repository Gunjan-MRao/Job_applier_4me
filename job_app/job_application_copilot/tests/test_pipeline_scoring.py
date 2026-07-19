"""
test_pipeline_scoring.py — unit tests for backend.pipeline.scoring.

Pure, deterministic scoring + sponsorship classification, no network/LLM.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline import scoring


# ---------------------------------------------------------------------------
# Sponsorship classifier
# ---------------------------------------------------------------------------

def test_classify_sponsorship_positive():
    assert scoring.classify_sponsorship("Visa sponsorship available for this role") == "yes"


def test_classify_sponsorship_negative():
    assert scoring.classify_sponsorship("You must already have the right to work in the UK") == "no"


def test_classify_sponsorship_unknown():
    assert scoring.classify_sponsorship("A great supply chain role in London") == "unknown"


def test_negative_beats_positive():
    text = "Visa sponsorship available. However we cannot sponsor at this time."
    assert scoring.classify_sponsorship(text) == "no"


# ---------------------------------------------------------------------------
# Fit scoring
# ---------------------------------------------------------------------------

PROFILE = {
    "candidate_name": "Bindu Sharma",
    "skills": ["supply chain", "logistics", "excel"],
    "years_of_experience_hint": "3 years",
}


def test_supply_chain_title_has_floor():
    job = {"title": "Logistics Coordinator", "description": ""}
    res = scoring.score_job(job, PROFILE, ["logistics"])
    assert res["fit_score"] >= 15
    assert res["fit_level"] in {"weak", "moderate", "strong"}


def test_keyword_matches_raise_score():
    job = {
        "title": "Supply Chain Analyst",
        "description": "supply chain analyst with logistics and procurement experience",
    }
    res = scoring.score_job(job, PROFILE, ["supply chain", "logistics", "procurement"])
    assert res["fit_score"] > 15
    assert any("keyword" in r for r in res["reasons"])


def test_senior_title_penalised_without_experience():
    junior = {"title": "Junior Supply Chain Analyst", "description": ""}
    senior = {"title": "Senior Supply Chain Manager", "description": ""}
    no_exp = {"skills": ["supply chain"], "years_of_experience_hint": ""}
    assert scoring.score_job(senior, no_exp, ["supply chain"])["fit_score"] < \
        scoring.score_job(junior, no_exp, ["supply chain"])["fit_score"]


def test_sponsorship_bonus_applied():
    job = {
        "title": "Supply Chain Analyst",
        "description": "supply chain role",
        "sponsorship_status": "yes",
    }
    res = scoring.score_job(job, PROFILE, ["supply chain"])
    assert any("sponsorship" in r for r in res["reasons"])


def test_skill_gaps_detected():
    job = {"title": "Analyst", "description": "must know sap and forecasting deeply for this position"}
    res = scoring.score_job(job, {"skills": ["excel"]}, ["analyst"])
    assert "sap" in res["gaps"]
    assert "forecasting" in res["gaps"]
