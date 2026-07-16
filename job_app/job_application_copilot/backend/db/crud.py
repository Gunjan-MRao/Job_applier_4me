"""
backend/db/crud.py  —  thin CRUD helpers used by API endpoints
"""
from typing import List, Optional
from backend.db.engine import SessionLocal


def _row_to_dict(row) -> dict:
    d = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def save_job(run_id: str, job: dict) -> None:
    from backend.models.job import Job
    db = SessionLocal()
    try:
        obj = Job(
            run_id=run_id,
            title=job.get("title"),
            company=job.get("company"),
            location=job.get("location"),
            salary=job.get("salary"),
            url=job.get("url"),
            source=job.get("source"),
            description=job.get("description"),
            sponsorship_status=job.get("sponsorship_status", "unknown"),
            visa_sponsored=bool(job.get("visa_sponsored")),
            fit_score=int(job.get("fit_score") or 0),
            fit_level=job.get("fit_level", "weak"),
            match_score=int(job.get("match_score") or 0),
            cover_letter=job.get("cover_letter"),
            cold_email=job.get("cold_email"),
            recruiter_email=job.get("recruiter_email"),
            date_posted=job.get("date_posted"),
        )
        db.add(obj)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def get_all_jobs(limit: int = 500) -> List[dict]:
    from backend.models.job import Job
    db = SessionLocal()
    try:
        rows = db.query(Job).order_by(Job.fit_score.desc()).limit(limit).all()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def get_jobs_by_run(run_id: str) -> List[dict]:
    from backend.models.job import Job
    db = SessionLocal()
    try:
        rows = db.query(Job).filter(Job.run_id == run_id).order_by(Job.fit_score.desc()).all()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def save_run(run: dict) -> None:
    from backend.models.run import Run
    import json
    db = SessionLocal()
    try:
        obj = Run(
            run_id=run["run_id"],
            candidate_email=run.get("candidate_email"),
            status=run.get("status", "queued"),
            stage=run.get("stage"),
            progress_percent=run.get("progress_percent", 0),
            result_summary=json.dumps(run.get("result_summary")) if run.get("result_summary") else None,
        )
        db.merge(obj)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def update_run_record(run_id: str, **kwargs) -> None:
    from backend.models.run import Run
    db = SessionLocal()
    try:
        db.query(Run).filter(Run.run_id == run_id).update(kwargs)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
