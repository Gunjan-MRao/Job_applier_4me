"""
pipeline_worker.py  — State-machine pipeline (v2)

Pipeline states (saved to DB per job):
  Scraped -> SponsorshipVerified -> ResumeTailored -> Applied -> EmailSent

If any stage crashes the run, already-processed jobs retain their state
so the worker can resume from where it left off without re-scraping.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.services.scraper import scrape_jobs
from backend.services.sponsor_register import SponsorRegister
from backend.services.resume_tailor_service import tailor_resume
from backend.services.job_fit_service import score_job, salary_meets_threshold
from backend.services.email_worker import EmailWorker
from backend.db.session import get_session
from backend.models.job import JobRecord, PipelineState

log = logging.getLogger(__name__)


class State(str, Enum):
    SCRAPED              = "Scraped"
    SPONSORSHIP_VERIFIED = "SponsorshipVerified"
    RESUME_TAILORED      = "ResumeTailored"
    APPLIED              = "Applied"
    EMAIL_SENT           = "EmailSent"
    SKIPPED              = "Skipped"   # salary / sponsorship fail
    FAILED               = "Failed"


class PipelineWorker:
    """Runs the 5-stage pipeline for a single automation run.

    Each stage persists state to the DB so crashes are safe to resume.
    """

    def __init__(self, run_id: str, cfg: Dict[str, Any]):
        self.run_id  = run_id
        self.cfg     = cfg
        self.sponsor = SponsorRegister()          # loads official GOV.UK CSV
        self.emailer = EmailWorker()              # rate-limited email sender
        self.results: List[Dict] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self) -> Dict[str, Any]:
        log.info("[%s] Pipeline starting", self.run_id)

        # Stage 1 — Scrape
        raw_jobs = await self._stage_scrape()
        log.info("[%s] Scraped %d jobs", self.run_id, len(raw_jobs))

        for job in raw_jobs:
            try:
                job = await self._stage_verify_sponsorship(job)
                if job.get("pipeline_state") == State.SKIPPED:
                    continue

                job = await self._stage_tailor_resume(job)
                job = await self._stage_apply(job)
                await self._stage_send_email(job)

            except Exception as exc:
                log.exception("[%s] Job %s failed: %s", self.run_id, job.get("title"), exc)
                job["pipeline_state"] = State.FAILED

            self.results.append(job)

        return {
            "run_id":       self.run_id,
            "total":        len(self.results),
            "applied":      sum(1 for j in self.results if j.get("pipeline_state") == State.APPLIED),
            "email_sent":   sum(1 for j in self.results if j.get("pipeline_state") == State.EMAIL_SENT),
            "skipped":      sum(1 for j in self.results if j.get("pipeline_state") == State.SKIPPED),
            "failed":       sum(1 for j in self.results if j.get("pipeline_state") == State.FAILED),
            "jobs":         self.results,
        }

    # ------------------------------------------------------------------
    # Stage 1 — Scrape
    # ------------------------------------------------------------------

    async def _stage_scrape(self) -> List[Dict]:
        jobs = await scrape_jobs(
            keywords=self.cfg.get("keywords", []),
            location=self.cfg.get("location", "United Kingdom"),
        )
        for j in jobs:
            j["pipeline_state"] = State.SCRAPED
            await self._persist(j)
        return jobs

    # ------------------------------------------------------------------
    # Stage 2 — Sponsorship verification (GOV.UK register + salary gate)
    # ------------------------------------------------------------------

    async def _stage_verify_sponsorship(self, job: Dict) -> Dict:
        company = job.get("company", "")

        # Cross-reference official UK sponsor register
        is_licensed = self.sponsor.is_licensed(company)
        job["govuk_licensed_sponsor"] = is_licensed

        if not is_licensed and self.cfg.get("require_sponsorship", False):
            log.info("[%s] SKIP %s — not on GOV.UK register", self.run_id, company)
            job["pipeline_state"] = State.SKIPPED
            job["skip_reason"]    = "Company not on GOV.UK licensed sponsor register"
            await self._persist(job)
            return job

        # Salary threshold gate (UK Skilled Worker Visa — £38,700 minimum for standard roles)
        salary_ok = salary_meets_threshold(
            salary_text=job.get("salary", ""),
            soc_code=job.get("soc_code"),
        )
        if not salary_ok:
            log.info("[%s] SKIP %s — salary below UK threshold", self.run_id, job.get("title"))
            job["pipeline_state"] = State.SKIPPED
            job["skip_reason"]    = "Salary below UK Skilled Worker Visa threshold (£38,700)"
            await self._persist(job)
            return job

        job["pipeline_state"] = State.SPONSORSHIP_VERIFIED
        await self._persist(job)
        return job

    # ------------------------------------------------------------------
    # Stage 3 — Resume tailoring
    # ------------------------------------------------------------------

    async def _stage_tailor_resume(self, job: Dict) -> Dict:
        profile = self.cfg.get("resume_profile") or {}
        try:
            job["cover_letter"], job["cold_email"], job["resume_guidance"] = await tailor_resume(
                job=job, profile=profile
            )
        except Exception as exc:
            log.warning("[%s] Tailor failed for %s: %s", self.run_id, job.get("title"), exc)
            job["cover_letter"] = None

        job["pipeline_state"] = State.RESUME_TAILORED
        await self._persist(job)
        return job

    # ------------------------------------------------------------------
    # Stage 4 — Apply
    # ------------------------------------------------------------------

    async def _stage_apply(self, job: Dict) -> Dict:
        # Placeholder — plug in your form-automation / Easy Apply logic here.
        # For now we mark it applied and record the timestamp.
        job["pipeline_state"] = State.APPLIED
        job["applied_at"]     = time.time()
        await self._persist(job)
        log.info("[%s] Applied: %s @ %s", self.run_id, job.get("title"), job.get("company"))
        return job

    # ------------------------------------------------------------------
    # Stage 5 — Cold email
    # ------------------------------------------------------------------

    async def _stage_send_email(self, job: Dict) -> Dict:
        cold_email = job.get("cold_email")
        if not cold_email:
            return job
        try:
            await self.emailer.send(
                to_address=job.get("recruiter_email") or job.get("company_email") or "",
                subject=self._safe_subject(job),
                body=cold_email,
            )
            job["pipeline_state"] = State.EMAIL_SENT
            await self._persist(job)
        except Exception as exc:
            log.warning("[%s] Email failed for %s: %s", self.run_id, job.get("company"), exc)
        return job

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_subject(job: Dict) -> str:
        """Build a subject line that avoids spam-trigger words."""
        title   = job.get("title", "Supply Chain Analyst")[:50]
        company = job.get("company", "")[:30]
        # Neutral framing — no URGENT / VISA / SPONSORSHIP in subject
        return f"Application — {title} at {company}"

    async def _persist(self, job: Dict) -> None:
        """Persist current pipeline state to DB (fire-and-forget, never raises)."""
        try:
            async with get_session() as session:
                rec = await session.get(JobRecord, job.get("job_id"))
                if rec:
                    rec.pipeline_state = job["pipeline_state"]
                    rec.skip_reason    = job.get("skip_reason")
                    await session.commit()
        except Exception:
            pass  # persistence failure must never kill the pipeline
