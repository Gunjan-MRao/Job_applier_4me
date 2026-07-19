"""
test_pipeline_orchestrator.py — integration tests for the rebuilt pipeline.

These exercise gather_jobs() (source priority: Adzuna -> Reed -> scraper ->
mock) and run_pipeline() end-to-end with the Adzuna/Reed adapters stubbed, so
they need no network and no credentials.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline import job_sources, orchestrator


PROFILE = {
    "candidate_name": "Bindu Sharma",
    "skills": ["supply chain", "logistics", "excel"],
    "years_of_experience_hint": "3 years",
}
KEYWORDS = ["supply chain analyst", "logistics coordinator"]

ADZUNA_STUB = [
    job_sources.make_job(
        "Supply Chain Analyst", "DHL", "Coventry", "£35,000",
        "http://x/1", "supply chain analyst; visa sponsorship available", "Adzuna",
    ),
]
REED_STUB = [
    job_sources.make_job(
        "Logistics Coordinator", "Maersk", "Liverpool", "£30,000",
        "http://x/2", "logistics coordinator role", "Reed",
    ),
]


# ---------------------------------------------------------------------------
# gather_jobs source priority
# ---------------------------------------------------------------------------

def test_gather_uses_adzuna_as_primary(monkeypatch):
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: list(ADZUNA_STUB))
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: [])
    out = orchestrator.gather_jobs(KEYWORDS, "United Kingdom")
    assert out["source_used"] == "Adzuna"
    assert out["used_mock"] is False
    assert any(j["source"] == "Adzuna" for j in out["jobs"])
    # sponsorship is classified on the way out
    assert out["jobs"][0]["sponsorship_status"] == "yes"


def test_gather_merges_reed_on_top_of_adzuna(monkeypatch):
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: list(ADZUNA_STUB))
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: list(REED_STUB))
    out = orchestrator.gather_jobs(KEYWORDS)
    sources = {j["source"] for j in out["jobs"]}
    assert {"Adzuna", "Reed"} <= sources


def test_gather_uses_reed_when_adzuna_empty(monkeypatch):
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: [])
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: list(REED_STUB))
    out = orchestrator.gather_jobs(KEYWORDS)
    assert out["source_used"] == "Reed"
    assert out["used_mock"] is False


def test_gather_falls_back_to_mock_when_no_live_source(monkeypatch):
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: [])
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: [])
    out = orchestrator.gather_jobs(KEYWORDS)
    assert out["source_used"] == "mock"
    assert out["used_mock"] is True
    assert len(out["jobs"]) >= 5
    assert any("mock" in n.lower() for n in out["notes"])


def test_gather_scraper_only_when_opted_in(monkeypatch):
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: [])
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: [])
    called = {"scraper": False}

    def fake_scraper(*a, **k):
        called["scraper"] = True
        return []

    monkeypatch.setattr(job_sources, "fetch_scraper_fallback", fake_scraper)
    # Default: scraper NOT called
    orchestrator.gather_jobs(KEYWORDS, allow_scraper_fallback=False)
    assert called["scraper"] is False
    # Opt-in: scraper IS attempted
    orchestrator.gather_jobs(KEYWORDS, allow_scraper_fallback=True)
    assert called["scraper"] is True


def test_gather_dedupes_by_title_company(monkeypatch):
    dup = list(ADZUNA_STUB) + list(ADZUNA_STUB)
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: dup)
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: [])
    out = orchestrator.gather_jobs(KEYWORDS)
    titles = [(j["title"], j["company"]) for j in out["jobs"]]
    assert len(titles) == len(set(titles))


# ---------------------------------------------------------------------------
# run_pipeline end-to-end
# ---------------------------------------------------------------------------

def test_run_pipeline_full_flow_with_stubbed_sources(monkeypatch):
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: list(ADZUNA_STUB))
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: list(REED_STUB))

    result = orchestrator.run_pipeline(
        PROFILE, KEYWORDS, "United Kingdom",
        min_fit_score=1, draft_top_n=5,
    )
    assert result["source_used"] == "Adzuna"
    assert result["jobs_scanned"] >= 2
    assert result["jobs_matched"] >= 1
    top = result["matches"][0]
    assert 0 <= top["fit_score"] <= 100
    # Top matches are drafted (offline template, no LLM supplied).
    assert top["cover_letter"].strip()
    assert top["cold_email"].strip().startswith("Subject:")


def test_run_pipeline_excludes_no_sponsorship(monkeypatch):
    no_spons = job_sources.make_job(
        "Supply Chain Analyst", "NoSponsorCo", "London", "£30,000",
        "http://x/3", "we cannot sponsor visas; must have right to work", "Adzuna",
    )
    monkeypatch.setattr(job_sources, "fetch_adzuna", lambda *a, **k: [no_spons])
    monkeypatch.setattr(job_sources, "fetch_reed", lambda *a, **k: [])

    result = orchestrator.run_pipeline(
        PROFILE, KEYWORDS, min_fit_score=1, exclude_no_sponsorship=True,
    )
    companies = {m["company"] for m in result["matches"]}
    assert "NoSponsorCo" not in companies
