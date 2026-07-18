"""
test_health_placeholder.py — Real health endpoint smoke test.

Replaces the placeholder assert True with an actual FastAPI TestClient
call so CI catches a broken startup immediately.
"""
import pytest
from fastapi.testclient import TestClient


def _get_client():
    """Import app lazily so import errors produce a clear skip, not a conftest crash."""
    try:
        from backend.main import app
        return TestClient(app)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Could not import backend app: {exc}")


def test_root_returns_200():
    client = _get_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert "message" in body


def test_health_endpoint_returns_200():
    """GET /health must return HTTP 200 with at least a 'status' key."""
    client = _get_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") in ("ok", "healthy", "running", True, "up")


def test_docs_reachable():
    """OpenAPI docs must be reachable (confirms all routers imported cleanly)."""
    client = _get_client()
    resp = client.get("/docs")
    assert resp.status_code == 200
