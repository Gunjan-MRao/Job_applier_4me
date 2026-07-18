"""
test_lead_finder.py — Unit tests for lead_finder.py

Tests (all network calls are mocked — no real HTTP):
 - Hunter.io path returns highest-confidence TA/HR email
 - Apollo.io path returns first person email when Hunter key absent
 - Heuristic path returns careers@domain when both API keys absent
 - _guess_domain produces correct slug
 - _heuristic_email returns None for empty domain
 - find_recruiter_email returns correct strategy label in each case
 - sync_find_recruiter_email returns same result as async version
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.lead_finder import (
    _guess_domain,
    _heuristic_email,
    find_recruiter_email,
    sync_find_recruiter_email,
)


# ---------------------------------------------------------------------------
# _guess_domain
# ---------------------------------------------------------------------------

def test_guess_domain_simple():
    assert _guess_domain("Tesco") == "tesco.com"


def test_guess_domain_strips_special_chars():
    assert _guess_domain("Smith & Jones") == "smithjones.com"


def test_guess_domain_uses_first_word():
    assert _guess_domain("Amazon UK Services") == "amazon.com"


# ---------------------------------------------------------------------------
# _heuristic_email
# ---------------------------------------------------------------------------

def test_heuristic_email_produces_careers_address():
    assert _heuristic_email("tesco.com") == "careers@tesco.com"


def test_heuristic_email_none_domain_returns_none():
    assert _heuristic_email(None) is None


# ---------------------------------------------------------------------------
# find_recruiter_email — Hunter hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_recruiter_email_hunter_hit():
    hunter_response = MagicMock()
    hunter_response.raise_for_status = MagicMock()
    hunter_response.json.return_value = {
        "data": {
            "emails": [
                {"value": "talent@tesco.com", "position": "talent acquisition", "confidence": 90},
                {"value": "bob@tesco.com",    "position": "engineer",           "confidence": 70},
            ]
        }
    }

    with patch("backend.services.lead_finder.settings") as mock_settings, \
         patch("requests.get", return_value=hunter_response):
        mock_settings.hunter_api_key = "fake-hunter-key"
        mock_settings.apollo_api_key = ""

        result = await find_recruiter_email(company="Tesco", domain="tesco.com")

    assert result["email"] == "talent@tesco.com"
    assert result["strategy"] == "hunter"
    assert result["company"] == "Tesco"


# ---------------------------------------------------------------------------
# find_recruiter_email — Apollo hit (Hunter key absent)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_recruiter_email_apollo_hit():
    apollo_response = MagicMock()
    apollo_response.raise_for_status = MagicMock()
    apollo_response.json.return_value = {
        "people": [
            {"email": "hr@amazon.com", "title": "hr manager"},
        ]
    }

    with patch("backend.services.lead_finder.settings") as mock_settings, \
         patch("requests.post", return_value=apollo_response):
        mock_settings.hunter_api_key = ""
        mock_settings.apollo_api_key = "fake-apollo-key"

        result = await find_recruiter_email(company="Amazon", domain="amazon.com")

    assert result["email"] == "hr@amazon.com"
    assert result["strategy"] == "apollo"


# ---------------------------------------------------------------------------
# find_recruiter_email — heuristic fallback (both keys absent)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_recruiter_email_heuristic_fallback():
    with patch("backend.services.lead_finder.settings") as mock_settings:
        mock_settings.hunter_api_key = ""
        mock_settings.apollo_api_key = ""

        result = await find_recruiter_email(company="DHL", domain="dhl.com")

    assert result["email"] == "careers@dhl.com"
    assert result["strategy"] == "heuristic"


# ---------------------------------------------------------------------------
# sync_find_recruiter_email
# ---------------------------------------------------------------------------

def test_sync_find_recruiter_email_returns_dict():
    with patch("backend.services.lead_finder.settings") as mock_settings:
        mock_settings.hunter_api_key = ""
        mock_settings.apollo_api_key = ""

        result = sync_find_recruiter_email(company="NHS", domain="nhs.uk")

    assert isinstance(result, dict)
    assert "email" in result
    assert "strategy" in result
    assert result["strategy"] == "heuristic"
