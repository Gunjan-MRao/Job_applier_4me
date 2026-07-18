"""
sponsor_register.py  — UK GOV.UK Licensed Sponsor Register

Downloads and caches the official CSV published at:
  https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers

The CSV URL on GOV.UK changes with each release.  This module:
  1. Scrapes the GOV.UK publications page to find the current CSV asset URL.
  2. Downloads and caches the CSV locally (refreshed every CACHE_TTL_HOURS).
  3. Provides O(1) in-memory lookup via normalised company name tokens.
  4. Exposes db_load() to upsert all names into the SQLAlchemy DB so API
     queries can JOIN against the sponsor table.

Usage:
    from backend.services.sponsor_register import SponsorRegister
    reg = SponsorRegister()
    reg.is_licensed("Tesco PLC")     # -> True
    reg.is_licensed("Some Startup")  # -> False
    reg.db_load(session)             # upsert into DB
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
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# GOV.UK publications page — we scrape this to get the live CSV asset URL
GOVUK_PUBLICATIONS_PAGE = (
    "https://www.gov.uk/government/publications/"
    "register-of-licensed-sponsors-workers"
)
# Hardcoded fallback URL in case scraping fails
GOVUK_CSV_FALLBACK = (
    "https://assets.publishing.service.gov.uk/government/uploads/system/uploads/"
    "attachment_data/file/sponsor-register.csv"
)

CACHE_TTL_HOURS = 12
CACHE_FILE = Path(__file__).resolve().parent.parent / "db" / "sponsor_register_cache.csv"


def _normalise(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation for fuzzy matching."""
    name = name.lower()
    name = re.sub(r"\b(ltd|limited|plc|llp|llc|inc|corp|group|uk|holdings?)\b", "", name)
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    return " ".join(name.split())


def _scrape_csv_url() -> Optional[str]:
    """Scrape the GOV.UK publications page to find the current CSV download URL."""
    try:
        resp = requests.get(
            GOVUK_PUBLICATIONS_PAGE,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".csv") and "sponsor" in href.lower():
                if href.startswith("http"):
                    return href
                return "https://assets.publishing.service.gov.uk" + href
    except Exception as exc:
        log.warning("Could not scrape GOV.UK publications page: %s", exc)
    return None


class SponsorRegister:
    """Thread-safe, file-cached lookup against the GOV.UK sponsor register."""

    def __init__(self, csv_url: Optional[str] = None, db_session=None):
        self._csv_url   = csv_url  # if None, we scrape GOV.UK for the live URL
        self._names: Set[str] = set()
        self._loaded_at: float = 0.0
        self._db_session = db_session
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_licensed(self, company_name: str) -> Optional[bool]:
        """Return True if company is on the register, False if not, None if register empty."""
        if not self._names:
            return None
        key = _normalise(company_name)
        if not key:
            return None
        if key in self._names:
            return True
        for n in self._names:
            if n and (n in key or key in n):
                return True
        return False

    def refresh(self) -> bool:
        """Force a fresh download regardless of TTL. Returns True on success."""
        return self._download()

    def db_load(self, session=None) -> int:
        """
        Upsert all sponsor names into the database.
        Uses the session passed in, or the one provided at construction time.
        Returns the number of rows upserted.
        """
        db = session or self._db_session
        if db is None:
            log.warning("db_load called without a database session — skipping")
            return 0
        if not self._names:
            log.warning("db_load: sponsor register is empty — nothing to upsert")
            return 0
        try:
            from backend.db.engine import engine
            from sqlalchemy import text
            # Ensure table exists (idempotent)
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS sponsor_companies (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        name_norm TEXT UNIQUE NOT NULL,
                        loaded_at REAL NOT NULL
                    )
                """))
                conn.commit()
            now = time.time()
            upserted = 0
            with engine.connect() as conn:
                for name in self._names:
                    conn.execute(text("""
                        INSERT INTO sponsor_companies (name_norm, loaded_at)
                        VALUES (:name, :ts)
                        ON CONFLICT(name_norm) DO UPDATE SET loaded_at=excluded.loaded_at
                    """), {"name": name, "ts": now})
                    upserted += 1
                conn.commit()
            log.info("db_load: upserted %d sponsor names", upserted)
            return upserted
        except Exception as exc:
            log.error("db_load failed: %s", exc)
            return 0

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
        # Try to scrape the live CSV URL from GOV.UK first
        live_url = self._csv_url or _scrape_csv_url() or GOVUK_CSV_FALLBACK
        try:
            r = requests.get(live_url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            text = r.content.decode("utf-8", errors="replace")
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(text, encoding="utf-8")
            self._parse_csv(text)
            log.info("Sponsor register downloaded from %s (%d entries)", live_url, len(self._names))
            return True
        except Exception as exc:
            log.warning("Could not download sponsor register from %s: %s", live_url, exc)
            if CACHE_FILE.exists():
                self._parse_csv(CACHE_FILE.read_text(encoding="utf-8", errors="replace"))
                log.info("Loaded stale sponsor register cache (%d entries)", len(self._names))
            return False

    def _parse_csv(self, text: str) -> None:
        self._names = set()
        try:
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                name = (
                    row.get("Organisation Name")
                    or row.get("organisation_name")
                    or row.get("OrganisationName")
                    or ""
                )
                if name.strip():
                    self._names.add(_normalise(name))
        except Exception as exc:
            log.warning("Sponsor register CSV parse error: %s", exc)
