"""
test_mock_banner.py — The mock/sample-data fallback must NEVER be silent.

Workstream B guarantee: whenever the pipeline serves built-in SAMPLE listings
(e.g. no job-search API keys), the UI must render a big, hard-to-miss RED banner
(``st.error``) that says these are not real jobs and names the missing keys.

These tests import the real Streamlit app module and drive the real banner
helper with a fake ``st`` recorder — no browser needed, so they always run.
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

pytest.importorskip("streamlit", reason="streamlit not installed")

import app as app_module


class _FakeSt:
    """Minimal recorder standing in for the streamlit module."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []

    def error(self, msg):
        self.errors.append(msg)

    def warning(self, msg):
        self.warnings.append(msg)

    def info(self, msg):
        self.infos.append(msg)


def test_mock_banner_renders_error_when_keys_missing(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(app_module, "st", fake)
    monkeypatch.setattr(app_module, "_missing_job_api_keys",
                        lambda: ["ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY"])

    app_module._render_mock_banner()

    assert len(fake.errors) == 1, "banner must use st.error (a prominent red banner)"
    msg = fake.errors[0]
    assert "SAMPLE DATA" in msg
    assert "NOT real job openings" in msg
    # It must name the missing keys so the user knows exactly what to fix.
    assert "ADZUNA_APP_ID" in msg
    assert "REED_API_KEY" in msg


def test_mock_banner_explains_no_results_when_keys_present(monkeypatch):
    """Keys present but sample data used -> banner still shows, different cause."""
    fake = _FakeSt()
    monkeypatch.setattr(app_module, "st", fake)
    monkeypatch.setattr(app_module, "_missing_job_api_keys", lambda: [])

    app_module._render_mock_banner()

    assert len(fake.errors) == 1
    msg = fake.errors[0]
    assert "SAMPLE DATA" in msg
    assert "no results" in msg or "could not be reached" in msg


def test_missing_keys_detected_from_blank_env(monkeypatch):
    """With no env vars and no secrets, all job-source keys report missing."""
    for k in app_module._JOB_SOURCE_KEYS:
        monkeypatch.delenv(k, raising=False)
    # Point the .env lookup at a nonexistent path so nothing leaks in.
    monkeypatch.setattr(app_module, "BASE_DIR", Path("/nonexistent-dir-xyz"))

    fake = _FakeSt()
    monkeypatch.setattr(app_module, "st", fake)
    missing = app_module._missing_job_api_keys()
    assert set(missing) == set(app_module._JOB_SOURCE_KEYS)


def test_pipeline_persists_used_mock_flag(monkeypatch):
    """Backend must record used_mock/source_used so the UI can render the banner.

    This closes the loop: gather -> run dict -> status response -> banner.
    """
    from backend.services import automation_runtime as ar
    from backend.pipeline import job_sources as _js
    from backend.pipeline import scoring as _sc
    from backend.schemas.automation import AutomationStartPayload, AutomationStatusResponse

    def _fake_gather(keywords, location="United Kingdom", allow_scraper_fallback=False, log_fn=None):
        jobs = _js.mock_jobs()
        for j in jobs:
            j.setdefault("sponsorship_status", _sc.classify_sponsorship(j.get("description", "")))
        return {"jobs": jobs, "source_used": "mock", "used_mock": True,
                "notes": ["stubbed: using mock listings"]}

    monkeypatch.setattr(ar, "_gather_jobs", _fake_gather)

    payload = AutomationStartPayload(
        candidate_email="user@example.com",
        keywords=["logistics coordinator"],
        location="United Kingdom",
        auto_apply=True,
    )
    run = ar.create_run(payload)
    ar.run_automation_pipeline(run["run_id"], payload)
    result = ar.get_run(run["run_id"])

    assert result["used_mock"] is True
    assert result["source_used"] == "mock"
    # The status schema must expose both fields to the frontend.
    resp = AutomationStatusResponse(**result)
    assert resp.used_mock is True
    assert resp.source_used == "mock"
