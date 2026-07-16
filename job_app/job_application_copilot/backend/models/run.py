"""
backend/models/run.py  —  SQLAlchemy ORM model for a pipeline run record
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime
from backend.db.engine import Base


class Run(Base):
    __tablename__ = "runs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    run_id           = Column(String(64), unique=True, index=True)
    candidate_email  = Column(String(256), nullable=True)
    status           = Column(String(32), default="queued")
    stage            = Column(String(256), nullable=True)
    progress_percent = Column(Integer, default=0)
    jobs_scanned     = Column(Integer, default=0)
    jobs_matched     = Column(Integer, default=0)
    jobs_applied     = Column(Integer, default=0)
    jobs_failed      = Column(Integer, default=0)
    result_summary   = Column(Text, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
