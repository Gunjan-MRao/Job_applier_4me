"""
tests/test_api.py  —  FastAPI endpoint smoke tests
Run with:  pytest tests/ -v
Requires:  pip install httpx
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)
    API_AVAILABLE = True
except Exception:
    API_AVAILABLE = False

import pytest


@pytest.mark.skipif(not API_AVAILABLE, reason="FastAPI app unavailable")
def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


@pytest.mark.skipif(not API_AVAILABLE, reason="FastAPI app unavailable")
def test_list_runs_returns_dict():
    resp = client.get("/automation/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert isinstance(body.get("runs"), list)


@pytest.mark.skipif(not API_AVAILABLE, reason="FastAPI app unavailable")
def test_get_unknown_run():
    resp = client.get("/automation/status/nonexistent-run-id")
    assert resp.status_code == 404
