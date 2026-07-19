"""
test_pipeline_e2e.py — End-to-end proof that the pipeline produces real output.

This test runs the FULL automation pipeline with the network scrapers stubbed
out (so it needs no paid credentials and no internet), which forces the built-in
fallback jobs through the REAL scoring and REAL offline draft-generation logic.

It codifies the guarantee the user cares about: given a resume, the pipeline
always produces at least one scored, matched job with a drafted cover letter and
cold email — even with zero API keys configured.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from backend.services import automation_runtime as ar
from backend.services.parser.resume_parser import build_profile_preview
from backend.schemas.automation import AutomationStartPayload

FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume.txt"


@pytest.fixture()
def profile():
    text = FIXTURE.read_text(encoding="utf-8")
    return build_profile_preview("Bindu_Sharma_Resume.txt", text)


def test_resume_parser_extracts_real_fields(profile):
    """Real parser logic must pull the key fields out of the sample resume."""
    assert profile["email"] == "bindu.sharma@example.com"
    assert "supply chain" in profile["skills"]
    assert "sap" in profile["skills"]
    # Years-of-experience heuristic should detect multi-year work history.
    assert profile["years_of_experience_hint"]


def test_pipeline_produces_drafted_application(monkeypatch, profile):
    """Full pipeline, no network, no API keys -> at least one drafted application.

    The pipeline's primary source is now Adzuna/Reed via
    ``backend.pipeline.orchestrator.gather_jobs``. With no API keys that source
    returns the realistic mock listings, so we force that deterministic path by
    stubbing the gather call to return the built-in mock jobs.
    """
    from backend.pipeline import job_sources as _js
    from backend.pipeline import scoring as _sc

    def _fake_gather(keywords, location="United Kingdom", allow_scraper_fallback=False, log_fn=None):
        jobs = _js.mock_jobs()
        for j in jobs:
            j.setdefault("sponsorship_status", _sc.classify_sponsorship(j.get("description", "")))
        return {"jobs": jobs, "source_used": "mock", "used_mock": True,
                "notes": ["stubbed: using mock listings"]}

    monkeypatch.setattr(ar, "_gather_jobs", _fake_gather)

    payload = AutomationStartPayload(
        candidate_email="bindu.sharma@example.com",
        keywords=["supply chain analyst", "logistics coordinator", "procurement analyst"],
        location="United Kingdom",
        auto_apply=True,
        resume_profile=profile,
    )

    run = ar.create_run(payload)
    run_id = run["run_id"]
    ar.run_automation_pipeline(run_id, payload)

    result = ar.get_run(run_id)
    assert result["status"] == "completed"
    assert result["jobs_scanned"] > 0
    assert result["jobs_matched"] > 0
    assert len(result["applied_jobs"]) > 0

    # At least one application must carry a real drafted cover letter + cold email.
    drafted = [
        j for j in result["applied_jobs"]
        if (j.get("cover_letter") or "").strip() and (j.get("cold_email") or "").strip()
    ]
    assert drafted, "expected at least one job with a drafted cover letter and cold email"

    top = max(drafted, key=lambda j: j.get("fit_score", 0))
    assert 0 <= top["fit_score"] <= 100
    # The offline cover letter is personalised with the candidate name + company.
    assert profile["candidate_name"].split()[0] in top["cover_letter"]
    assert top["company"] in top["cover_letter"]


def test_offline_generation_is_used_without_keys(monkeypatch, profile):
    """With no LLM key, _llm returns None and offline templates fill the gap."""
    monkeypatch.setattr(ar, "_groq", lambda *a, **k: None)
    monkeypatch.setattr(ar, "_gemini", lambda *a, **k: None)
    monkeypatch.setattr(ar, "_huggingface", lambda *a, **k: None)
    monkeypatch.setattr(ar, "_openai_llm", lambda *a, **k: None)
    monkeypatch.setattr(ar, "_anthropic_llm", lambda *a, **k: None)

    job = ar.FALLBACK_JOBS[0]
    letter = ar.generate_cover_letter(profile, job)
    email = ar.generate_cold_email(profile, job)

    assert job["company"] in letter
    assert "Subject:" in email
