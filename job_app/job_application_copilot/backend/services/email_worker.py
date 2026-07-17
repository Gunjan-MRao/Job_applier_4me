"""
email_worker.py  — Rate-limited, spam-safe cold email sender

Rules enforced:
  - Maximum MAX_PER_DAY emails per calendar day (default 25)
  - Random delay of DELAY_MIN_S–DELAY_MAX_S seconds between each send
  - Subject line sanitised to strip known spam-trigger words
  - Daily counter persisted to a lightweight JSON file so it survives restarts

Usage:
    worker = EmailWorker()
    await worker.send(to_address="hr@company.com", subject="...", body="...")
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import smtplib
import ssl
import time
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from backend.core.config import settings

log = logging.getLogger(__name__)

MAX_PER_DAY  = 25
DELAY_MIN_S  = 15 * 60   # 15 minutes
DELAY_MAX_S  = 45 * 60   # 45 minutes
COUNTER_FILE = Path(__file__).resolve().parent.parent / "db" / "email_counter.json"

# Words that reliably trigger spam filters in subject lines
_SPAM_WORDS = re.compile(
    r"\b(urgent|asap|visa sponsorship required|sponsorship needed|immediately|"
    r"free|guaranteed|winner|congratulations|click here|apply now)\b",
    re.IGNORECASE,
)


class EmailWorker:

    def __init__(self):
        self._counter: dict = self._load_counter()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        from_name: Optional[str] = None,
    ) -> bool:
        """Send a single cold email, respecting rate limits.

        Returns True on success, False if daily cap reached or send fails.
        """
        today = str(date.today())
        sent_today = self._counter.get(today, 0)

        if sent_today >= MAX_PER_DAY:
            log.warning("Daily email cap (%d) reached — skipping %s", MAX_PER_DAY, to_address)
            return False

        if not to_address or "@" not in to_address:
            log.debug("No valid recipient address — skipping email")
            return False

        clean_subject = self._sanitise_subject(subject)

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._smtp_send(to_address, clean_subject, body, from_name),
            )
            self._counter[today] = sent_today + 1
            self._save_counter()
            log.info("Email sent to %s (%d/%d today)", to_address, sent_today + 1, MAX_PER_DAY)

            # Throttle: wait a random interval before the caller can send next
            delay = random.uniform(DELAY_MIN_S, DELAY_MAX_S)
            log.debug("Email throttle: sleeping %.0f s", delay)
            await asyncio.sleep(delay)
            return True

        except Exception as exc:
            log.error("Email send failed to %s: %s", to_address, exc)
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitise_subject(subject: str) -> str:
        """Remove spam-trigger words from subject line."""
        return _SPAM_WORDS.sub("", subject).strip()

    @staticmethod
    def _smtp_send(to: str, subject: str, body: str, from_name: Optional[str]) -> None:
        sender = settings.email_address
        if not sender:
            raise ValueError("EMAIL_ADDRESS not configured in settings")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{from_name or 'Job Copilot'} <{sender}>"
        msg["To"]      = to
        msg.attach(MIMEText(body, "plain", "utf-8"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx) as srv:
            srv.login(settings.email_address, settings.email_password)
            srv.sendmail(sender, [to], msg.as_string())

    def _load_counter(self) -> dict:
        try:
            if COUNTER_FILE.exists():
                return json.loads(COUNTER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_counter(self) -> None:
        try:
            COUNTER_FILE.parent.mkdir(parents=True, exist_ok=True)
            COUNTER_FILE.write_text(json.dumps(self._counter), encoding="utf-8")
        except Exception:
            pass
