"""
backend/core/config.py
Centralised settings — reads from .env (or environment variables).
All optional; the pipeline runs fully offline with zero API keys.
"""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM keys (all optional — free/offline fallbacks always work)
    gemini_api_key:    Optional[str] = None
    hf_api_key:        Optional[str] = None
    openai_api_key:    Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # Adzuna free API (100 results/call, get keys at developer.adzuna.com)
    adzuna_app_id:  Optional[str] = None
    adzuna_app_key: Optional[str] = None

    # App internals
    database_url: str = "sqlite:///./storage/jobs.db"
    secret_key:   str = "change-me-in-production"
    debug:        bool = False


settings = Settings()
