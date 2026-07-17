"""
config.py — Central settings (reads from environment / .env file)

Add your API keys to a .env file in the project root:

    GEMINI_API_KEY=...
    HUNTER_API_KEY=...
    APOLLO_API_KEY=...
    EMAIL_ADDRESS=your@gmail.com
    EMAIL_PASSWORD=app-specific-password
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=465
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
except ImportError:
    pass


class _Settings:
    gemini_api_key:   str = os.getenv("GEMINI_API_KEY",   "")
    openai_api_key:   str = os.getenv("OPENAI_API_KEY",   "")
    anthropic_api_key:str = os.getenv("ANTHROPIC_API_KEY","")
    hunter_api_key:   str = os.getenv("HUNTER_API_KEY",   "")
    apollo_api_key:   str = os.getenv("APOLLO_API_KEY",   "")
    email_address:    str = os.getenv("EMAIL_ADDRESS",     "")
    email_password:   str = os.getenv("EMAIL_PASSWORD",    "")
    smtp_host:        str = os.getenv("SMTP_HOST",         "smtp.gmail.com")
    smtp_port:        int = int(os.getenv("SMTP_PORT",     "465"))


settings = _Settings()
