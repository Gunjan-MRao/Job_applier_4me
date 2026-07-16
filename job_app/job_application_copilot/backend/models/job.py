"""
backend/models/job.py  —  SQLAlchemy ORM model for a scraped job
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean
from backend.db.engine import Base


class Job(Base):
    __tablename__ = "jobs"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    run_id             = Column(String(64), index=True, nullable=True)
    title              = Column(String(256))
    company            = Column(String(256))
    location           = Column(String(256))
    salary             = Column(String(128), nullable=True)
    url                = Column(Text, nullable=True)
    source             = Column(String(128), nullable=True)
    description        = Column(Text, nullable=True)
    sponsorship_status = Column(String(16), default="unknown")
    visa_sponsored     = Column(Boolean, default=False)
    fit_score          = Column(Integer, default=0)
    fit_level          = Column(String(16), default="weak")
    match_score        = Column(Integer, default=0)
    cover_letter       = Column(Text, nullable=True)
    cold_email         = Column(Text, nullable=True)
    recruiter_email    = Column(String(256), nullable=True)
    date_posted        = Column(String(64), nullable=True)
    scraped_at         = Column(DateTime, default=datetime.utcnow)
