"""
backend/db/engine.py  —  SQLAlchemy engine + session factory
Creates storage/jobs.db automatically on first run.
"""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

_DB_PATH = Path("storage")
_DB_PATH.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./storage/jobs.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables (called once at startup)."""
    from backend.models import Job, Run  # noqa: F401  — registers models with Base
    Base.metadata.create_all(bind=engine)
