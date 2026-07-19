"""
test_job_sources.py — unit tests for the rebuilt job-data sources.

These cover the new PRIMARY (Adzuna) and SECONDARY (Reed) API adapters with the
network fully stubbed using realistic fixture JSON that matches each provider's
actual response schema, plus the always-available mock listings. No network,
no credentials, no paid APIs.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from backend.pipeline import job_sources as js

FIXTURES = Path(__file__).parent / "fixtures"
ADZUNA_JSON = json.loads((FIXTURES / "adzuna_response.json").read_text())
REED_JSON = json.loads((FIXTURES / "reed_response.json").read_text())


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeSession:
    """Returns `payload` on the first GET, then an empty result set so paged
    fetchers terminate deterministically."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status = status_code
        self.calls = []

    def get(self, url, params=None, timeout=None, auth=None):
        self.calls.append({"url": url, "params": params, "auth": auth})
        if len(self.calls) == 1:
            return _FakeResponse(self._payload, self._status)
        return _FakeResponse({"results": []}, 200)


# ---------------------------------------------------------------------------
# make_job / salary formatting
# ---------------------------------------------------------------------------

def test_make_job_canonical_shape():
    job = js.make_job("Analyst", "ACME", "London", "£30,000", "http://x", "desc", "Adzuna")
    assert set(job) >= {
        "title", "company", "location", "salary", "url",
        "description", "source", "recruiter_email", "date_posted",
    }
    assert job["source"] == "Adzuna"


def test_make_job_rejects_empty_title():
    assert js.make_job("", "ACME", "London", "", "", "", "Adzuna") is None


def test_make_job_cleans_nan_placeholders():
    job = js.make_job("Analyst", "nan", "N/A", "-", "", "", "Reed")
    assert job["company"] == "Unknown"
    assert job["location"] == "United Kingdom"


def test_format_salary_range_and_single():
    assert js._format_salary(30000, 40000) == "£30,000–£40,000"
    assert js._format_salary(30000, None) == "£30,000"
    assert js._format_salary(None, None) == ""


# ---------------------------------------------------------------------------
# Adzuna (PRIMARY)
# ---------------------------------------------------------------------------

def test_fetch_adzuna_no_credentials_returns_empty(monkeypatch):
    monkeypatch.setattr(js, "adzuna_credentials", lambda: ("", ""))
    assert js.fetch_adzuna("supply chain") == []


def test_fetch_adzuna_parses_real_schema(monkeypatch):
    monkeypatch.setattr(js, "adzuna_credentials", lambda: ("id", "key"))
    sess = _FakeSession(ADZUNA_JSON)
    jobs = js.fetch_adzuna("supply chain analyst", "Coventry", pages=1, session=sess)

    assert len(jobs) == 3
    first = jobs[0]
    assert first["title"] == "Supply Chain Analyst"
    assert first["company"] == "DHL Supply Chain"
    assert first["location"] == "Coventry, West Midlands"
    assert first["salary"] == "£32,000–£38,000"
    assert first["url"] == "https://www.adzuna.co.uk/jobs/details/4001"
    assert first["source"] == "Adzuna"
    assert first["date_posted"] == "2026-07-10"
    # app_id / app_key are passed through as query params
    assert sess.calls[0]["params"]["app_id"] == "id"
    assert sess.calls[0]["params"]["app_key"] == "key"


def test_fetch_adzuna_handles_401(monkeypatch):
    monkeypatch.setattr(js, "adzuna_credentials", lambda: ("id", "badkey"))
    sess = _FakeSession({"results": []}, status_code=401)
    assert js.fetch_adzuna("supply chain", pages=2, session=sess) == []


# ---------------------------------------------------------------------------
# Reed (SECONDARY)
# ---------------------------------------------------------------------------

def test_fetch_reed_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(js, "reed_api_key", lambda: "")
    assert js.fetch_reed("supply chain") == []


def test_fetch_reed_parses_real_schema(monkeypatch):
    monkeypatch.setattr(js, "reed_api_key", lambda: "reed-key")
    sess = _FakeSession(REED_JSON)
    jobs = js.fetch_reed("demand planner", "Leeds", session=sess)

    assert len(jobs) == 2
    first = jobs[0]
    assert first["title"] == "Demand Planner"
    assert first["company"] == "Unilever"
    assert first["salary"] == "£35,000–£42,000"
    assert first["source"] == "Reed"
    # Reed uses HTTP Basic auth: API key as username, blank password
    assert sess.calls[0]["auth"] == ("reed-key", "")


# ---------------------------------------------------------------------------
# Mock (LAST RESORT)
# ---------------------------------------------------------------------------

def test_mock_jobs_are_realistic_and_isolated():
    a = js.mock_jobs()
    b = js.mock_jobs()
    assert len(a) >= 5
    assert all(j["title"] and j["company"] for j in a)
    # Fresh copies each call — mutating one must not leak into the next.
    a[0]["title"] = "MUTATED"
    assert b[0]["title"] != "MUTATED"
