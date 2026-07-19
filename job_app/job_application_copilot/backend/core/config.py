"""
config.py — Central settings (reads from environment / .env file)

Copy .env.example to .env in the job_application_copilot/ folder and fill in
your values. The app is designed to run 100% free:

    GROQ_API_KEY=...            # free LLM  (https://console.groq.com)
    EMAIL_ADDRESS=you@gmail.com # SMTP sender for cold emails
    EMAIL_PASSWORD=app-password # Gmail App Password, NOT your login password
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=465

Everything has a safe default, so the app never crashes when a key is missing —
it simply falls back to offline templates / keyless job sources.
"""
from __future__ import annotations

import os
from pathlib import Path

# The .env file lives in the project root (job_application_copilot/), which is
# two levels up from this file (backend/core/config.py -> backend -> project).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class _Settings:
    # App metadata
    app_name:          str  = os.getenv("APP_NAME",  "Job Application Copilot")
    app_env:           str  = os.getenv("APP_ENV",   "development")
    debug:             bool = os.getenv("DEBUG",     "false").lower() == "true"

    # Database (SQLite by default — file lives inside the project folder)
    database_url:      str = os.getenv(
        "DATABASE_URL", f"sqlite:///{_PROJECT_ROOT / 'storage' / 'jobs.db'}"
    )

    # LLM providers — Groq is the free primary; the rest are optional fallbacks
    groq_api_key:      str = os.getenv("GROQ_API_KEY",      "")
    gemini_api_key:    str = os.getenv("GEMINI_API_KEY",    "")
    hf_api_key:        str = os.getenv("HF_API_KEY",        "")
    openai_api_key:    str = os.getenv("OPENAI_API_KEY",    "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Job search (all optional / keyless-friendly)
    # Adzuna is the PRIMARY job source, Reed the secondary. Both are free,
    # official JSON APIs — no scraping/anti-bot risk. When unset, the pipeline
    # falls back to clearly-labelled mock listings so the flow is still demoable.
    adzuna_app_id:     str = os.getenv("ADZUNA_APP_ID",     "")
    adzuna_app_key:    str = os.getenv("ADZUNA_APP_KEY",    "")
    reed_api_key:      str = os.getenv("REED_API_KEY",      "")

    # Lead finder (optional)
    hunter_api_key:    str = os.getenv("HUNTER_API_KEY",    "")
    apollo_api_key:    str = os.getenv("APOLLO_API_KEY",    "")

    # Email / SMTP (free cold-email sending via e.g. Gmail App Password)
    # EMAIL_ADDRESS / EMAIL_PASSWORD are the canonical names; SMTP_USER /
    # SMTP_PASS are accepted as aliases for convenience.
    email_address:     str = os.getenv("EMAIL_ADDRESS") or os.getenv("SMTP_USER", "")
    email_password:    str = os.getenv("EMAIL_PASSWORD") or os.getenv("SMTP_PASS", "")
    smtp_host:         str = os.getenv("SMTP_HOST",      "smtp.gmail.com")
    smtp_port:         int = _get_int("SMTP_PORT", 465)

    # Storage paths (relative to project root unless absolute)
    storage_dir:       str = os.getenv("STORAGE_DIR",    "storage")
    resume_dir:        str = os.getenv("RESUME_DIR",     "storage/resumes")
    generated_dir:     str = os.getenv("GENERATED_DIR",  "storage/generated")
    screenshot_dir:    str = os.getenv("SCREENSHOT_DIR", "storage/screenshots")
    log_dir:           str = os.getenv("LOG_DIR",        "storage/logs")


settings = _Settings()
