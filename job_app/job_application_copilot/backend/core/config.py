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
    # override=True: always write .env values into os.environ regardless of
    # import order. Without this, if any module touched os.environ before
    # config.py loaded, our keys would silently read as empty strings.
    load_dotenv(_PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class _Settings:
    """Lazy-read settings: every attribute calls os.getenv() at access time,
    not at import time, so load_dotenv() is always guaranteed to have run first.
    """

    # -- App metadata --
    @property
    def app_name(self) -> str:  return os.getenv("APP_NAME",  "Job Application Copilot")
    @property
    def app_env(self) -> str:   return os.getenv("APP_ENV",   "development")
    @property
    def debug(self) -> bool:    return os.getenv("DEBUG", "false").lower() == "true"

    # -- Database --
    @property
    def database_url(self) -> str:
        return os.getenv(
            "DATABASE_URL",
            f"sqlite:///{_PROJECT_ROOT / 'storage' / 'jobs.db'}"
        )

    # -- LLM providers (Groq = free primary; rest = optional fallbacks) --
    @property
    def groq_api_key(self) -> str:      return os.getenv("GROQ_API_KEY",      "")
    @property
    def gemini_api_key(self) -> str:    return os.getenv("GEMINI_API_KEY",    "")
    @property
    def hf_api_key(self) -> str:        return os.getenv("HF_API_KEY",        "")
    @property
    def openai_api_key(self) -> str:    return os.getenv("OPENAI_API_KEY",    "")
    @property
    def anthropic_api_key(self) -> str: return os.getenv("ANTHROPIC_API_KEY", "")

    # -- Job search APIs --
    # Adzuna = PRIMARY (free, official JSON REST, UK-focused)
    # Reed   = SECONDARY (free, official JSON REST, UK-focused)
    # Both require keys; without them the pipeline falls back to mock listings.
    @property
    def adzuna_app_id(self) -> str:  return os.getenv("ADZUNA_APP_ID",  "")
    @property
    def adzuna_app_key(self) -> str: return os.getenv("ADZUNA_APP_KEY", "")
    @property
    def reed_api_key(self) -> str:   return os.getenv("REED_API_KEY",   "")

    # -- Lead finder (optional) --
    @property
    def hunter_api_key(self) -> str: return os.getenv("HUNTER_API_KEY", "")
    @property
    def apollo_api_key(self) -> str: return os.getenv("APOLLO_API_KEY", "")

    # -- Email / SMTP --
    # EMAIL_ADDRESS / EMAIL_PASSWORD are canonical; SMTP_USER / SMTP_PASS accepted as aliases.
    @property
    def email_address(self) -> str:  return os.getenv("EMAIL_ADDRESS") or os.getenv("SMTP_USER", "")
    @property
    def email_password(self) -> str: return os.getenv("EMAIL_PASSWORD") or os.getenv("SMTP_PASS", "")
    @property
    def smtp_host(self) -> str:      return os.getenv("SMTP_HOST", "smtp.gmail.com")
    @property
    def smtp_port(self) -> int:      return _get_int("SMTP_PORT", 465)

    # -- Storage paths (relative to project root unless absolute) --
    @property
    def storage_dir(self) -> str:    return os.getenv("STORAGE_DIR",    "storage")
    @property
    def resume_dir(self) -> str:     return os.getenv("RESUME_DIR",     "storage/resumes")
    @property
    def generated_dir(self) -> str:  return os.getenv("GENERATED_DIR",  "storage/generated")
    @property
    def screenshot_dir(self) -> str: return os.getenv("SCREENSHOT_DIR", "storage/screenshots")
    @property
    def log_dir(self) -> str:        return os.getenv("LOG_DIR",        "storage/logs")


settings = _Settings()
