"""
backend/services/generate/generator.py
Single public entry point for all LLM text generation.
"""
from backend.services.automation_runtime import (
    generate_cover_letter,
    generate_cold_email,
    generate_resume_tailoring,
)

__all__ = ["generate_cover_letter", "generate_cold_email", "generate_resume_tailoring"]
