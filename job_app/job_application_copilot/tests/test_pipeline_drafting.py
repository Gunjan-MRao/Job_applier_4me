"""
test_pipeline_drafting.py — unit tests for backend.pipeline.drafting.

The LLM is injected as a stub callable, so these tests prove both the
LLM-first path and the offline-template fallback (no API key) without any
network access.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline import drafting


PROFILE = {
    "candidate_name": "Bindu Sharma",
    "skills": ["supply chain", "logistics", "sap", "excel"],
    "years_of_experience_hint": "3 years",
    "likely_roles": ["supply chain analyst"],
}
JOB_YES = {
    "title": "Supply Chain Analyst",
    "company": "DHL Supply Chain",
    "description": "SAP and Excel essential. Visa sponsorship available.",
    "sponsorship_status": "yes",
}
JOB_NO = {
    "title": "Logistics Coordinator",
    "company": "Kuehne+Nagel",
    "description": "You must already have the right to work in the UK.",
    "sponsorship_status": "no",
}


# ---------------------------------------------------------------------------
# Offline templates (no LLM)
# ---------------------------------------------------------------------------

def test_offline_cover_letter_personalised():
    letter = drafting.offline_cover_letter(PROFILE, JOB_YES)
    assert "Bindu" in letter
    assert JOB_YES["company"] in letter
    assert "Certificate of Sponsorship" in letter  # spons == yes -> disclosed


def test_offline_cover_letter_omits_sponsorship_when_no():
    letter = drafting.offline_cover_letter(PROFILE, JOB_NO)
    assert "Certificate of Sponsorship" not in letter


def test_offline_cold_email_has_subject_and_company():
    email = drafting.offline_cold_email(PROFILE, JOB_YES)
    assert email.startswith("Subject:")
    assert JOB_YES["company"] in email


def test_offline_cold_email_omits_sponsorship_when_no():
    email = drafting.offline_cold_email(PROFILE, JOB_NO)
    assert "Certificate of Sponsorship" not in email


# ---------------------------------------------------------------------------
# LLM-first with injected stub
# ---------------------------------------------------------------------------

def test_draft_cover_letter_uses_llm_when_available():
    calls = {}

    def fake_llm(prompt, max_tokens=0):
        calls["prompt"] = prompt
        return "LLM COVER LETTER OUTPUT"

    out = drafting.draft_cover_letter(PROFILE, JOB_YES, llm_fn=fake_llm)
    assert out == "LLM COVER LETTER OUTPUT"
    assert "DHL Supply Chain" in calls["prompt"]


def test_draft_cold_email_uses_llm_when_available():
    out = drafting.draft_cold_email(PROFILE, JOB_YES, llm_fn=lambda *a, **k: "LLM EMAIL")
    assert out == "LLM EMAIL"


def test_draft_falls_back_to_offline_when_llm_returns_none():
    out = drafting.draft_cover_letter(PROFILE, JOB_YES, llm_fn=lambda *a, **k: None)
    assert "Bindu" in out  # offline template


def test_draft_falls_back_to_offline_when_llm_raises():
    def boom(*a, **k):
        raise RuntimeError("provider down")

    out = drafting.draft_cold_email(PROFILE, JOB_YES, llm_fn=boom)
    assert out.startswith("Subject:")  # offline template used


def test_draft_uses_offline_when_no_llm_supplied():
    out = drafting.draft_cover_letter(PROFILE, JOB_YES)  # llm_fn=None
    assert JOB_YES["company"] in out
