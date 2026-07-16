"""
backend/services/match/scorer.py
Weighted keyword scorer — same SC_KEYWORDS vocabulary used by scraper.py.
Can be called standalone: score_job(job_dict) -> int
"""
from backend.services.jobs.scraper import SC_KEYWORDS, NEGATIVE, score_job

__all__ = ["SC_KEYWORDS", "NEGATIVE", "score_job"]
