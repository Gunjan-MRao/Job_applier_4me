"""
test_sponsor_register.py — Unit tests for SponsorRegister.

Tests:
 - _normalise() strips legal suffixes correctly
 - is_licensed() returns True for known sponsor, False for unknown
 - is_licensed() returns None when register is empty
 - _parse_csv() handles alternate column names (organisation_name)
 - _download() falls back to stale cache when network fails
 - db_load() skips gracefully when no session provided
"""
import io
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.sponsor_register import SponsorRegister, _normalise


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------

def test_normalise_strips_ltd():
    assert _normalise("Tesco Ltd") == "tesco"


def test_normalise_strips_plc():
    assert _normalise("Unilever PLC") == "unilever"


def test_normalise_strips_punctuation():
    result = _normalise("Smith & Jones, LLP")
    assert "smith" in result
    assert "jones" in result
    assert "llp" not in result


def test_normalise_empty_string():
    assert _normalise("") == ""


# ---------------------------------------------------------------------------
# SponsorRegister with mocked CSV
# ---------------------------------------------------------------------------

SAMPLE_CSV = "Organisation Name,Town/City,County,Type & Rating,Route\n"\
             "Tesco PLC,Welwyn Garden City,Hertfordshire,A (Premium),Skilled Worker\n"\
             "Amazon UK Services Ltd,London,Greater London,A (Premium),Skilled Worker\n"\
             "NHS Supply Chain,Redditch,Worcestershire,A (Premium),Skilled Worker\n"


def _make_register(csv_text: str = SAMPLE_CSV) -> SponsorRegister:
    """Create a SponsorRegister without hitting the network."""
    reg = SponsorRegister.__new__(SponsorRegister)
    reg._csv_url   = None
    reg._names     = set()
    reg._loaded_at = 0.0
    reg._db_session = None
    reg._parse_csv(csv_text)
    return reg


def test_is_licensed_known_sponsor():
    reg = _make_register()
    assert reg.is_licensed("Tesco") is True


def test_is_licensed_known_sponsor_with_suffix():
    reg = _make_register()
    assert reg.is_licensed("Amazon UK Services Ltd") is True


def test_is_licensed_unknown_company():
    reg = _make_register()
    assert reg.is_licensed("Totally Unknown Startup XYZ") is False


def test_is_licensed_empty_register_returns_none():
    reg = _make_register("Organisation Name\n")  # header only
    assert reg.is_licensed("Tesco") is None


def test_is_licensed_empty_name_returns_none():
    reg = _make_register()
    assert reg.is_licensed("") is None


def test_parse_csv_alternate_column_name():
    alt_csv = "organisation_name,city\nDHL Limited,London\n"
    reg = _make_register(alt_csv)
    assert reg.is_licensed("DHL") is True


# ---------------------------------------------------------------------------
# _download fallback to stale cache
# ---------------------------------------------------------------------------

def test_download_uses_stale_cache_on_network_failure(tmp_path, monkeypatch):
    cache = tmp_path / "sponsor_register_cache.csv"
    cache.write_text(SAMPLE_CSV, encoding="utf-8")

    monkeypatch.setattr(
        "backend.services.sponsor_register.CACHE_FILE", cache
    )

    def bad_get(*args, **kwargs):
        raise ConnectionError("Network down")

    monkeypatch.setattr("requests.get", bad_get)

    reg = SponsorRegister.__new__(SponsorRegister)
    reg._csv_url    = "http://fake"
    reg._names      = set()
    reg._loaded_at  = 0.0
    reg._db_session = None
    success = reg._download()

    assert success is False
    assert len(reg._names) > 0  # stale cache was loaded


# ---------------------------------------------------------------------------
# db_load without session
# ---------------------------------------------------------------------------

def test_db_load_no_session_returns_zero():
    reg = _make_register()
    result = reg.db_load(session=None)
    assert result == 0
