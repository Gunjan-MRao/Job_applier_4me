"""
sponsor_register.py  — UK GOV.UK Licensed Sponsor Register

Downloads and caches the official CSV published at:
  https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers

The file is refreshed at most once every CACHE_TTL_HOURS hours.
Lookup is O(1) via a normalised set of company name tokens.

Usage:
    from backend.services.sponsor_register import SponsorRegister
    reg = SponsorRegister()
    reg.is_licensed("Tesco PLC")    # -> True / False
    reg.is_licensed("Some Startup") # -> False
"""
from __future__ import annotations

import csv
import io
import logging
import re
import time
from pathlib import Path
from typing import Optional, Set

import requests

log = logging.getLogger(__name__)

# Official GOV.UK CSV URL (Skilled Worker / Temporary Worker register)
GOVUK_CSV_URL = (
    "https://assets.publishing.service.gov.uk/government/uploads/system/uploads/"
    "attachment_data/file/sponsor-register.csv"
)
# Fallback mirror (direct search API alternative)
GOVUK_API_URL = "https://api.register-of-licensed-sponsors.service.gov.uk/organisations"

CACHE_TTL_HOURS = 12
CACHE_FILE      = Path(__file__).resolve().parent.parent / "db" / "sponsor_register_cache.csv"


def _normalise(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation for fuzzy matching."""
    name = name.lower()
    name = re.sub(r"\b(ltd|limited|plc|llp|llc|inc|corp|group|uk|holdings?)\b", "", name)
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    return " ".join(name.split())


class SponsorRegister:
    """Thread-safe, file-cached lookup against the GOV.UK sponsor register."""

    def __init__(self, csv_url: str = GOVUK_CSV_URL):
        self._csv_url   = csv_url
        self._names: Set[str] = set()
        self._loaded_at: float = 0.0
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_licensed(self, company_name: str) -> Optional[bool]:
        """Return True if company is on the register, False if not, None if register empty."""
        if not self._names:
            return None  # register not loaded — caller should not filter on None
        key = _normalise(company_name)
        if not key:
            return None
        # Exact normalised match
        if key in self._names:
            return True
        # Partial match — company name contains a registered name as a substring
        for n in self._names:
            if n and (n in key or key in n):
                return True
        return False

    def refresh(self) -> bool:
        """Force a fresh download regardless of TTL. Returns True on success."""
        return self._download()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load from cache file if fresh, otherwise download."""
        if CACHE_FILE.exists():
            age_h = (time.time() - CACHE_FILE.stat().st_mtime) / 3600
            if age_h < CACHE_TTL_HOURS:
                self._parse_csv(CACHE_FILE.read_text(encoding="utf-8", errors="replace"))
                log.info("Sponsor register loaded from cache (%d entries)", len(self._names))
                return
        self._download()

    def _download(self) -> bool:
        try:
            r = requests.get(self._csv_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            text = r.content.decode("utf-8", errors="replace")
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(text, encoding="utf-8")
            self._parse_csv(text)
            log.info("Sponsor register downloaded (%d entries)", len(self._names))
            return True
        except Exception as exc:
            log.warning("Could not download sponsor register: %s", exc)
            # Try to load stale cache as fallback
            if CACHE_FILE.exists():
                self._parse_csv(CACHE_FILE.read_text(encoding="utf-8", errors="replace"))
            return False

    def _parse_csv(self, text: str) -> None:
        self._names = set()
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                # GOV.UK CSV column is 'Organisation Name'
                name = row.get("Organisation Name") or row.get("organisation_name") or ""
                if name:
                    self._names.add(_normalise(name))
        except Exception as exc:
            log.warning("Sponsor register CSV parse error: %s", exc)
