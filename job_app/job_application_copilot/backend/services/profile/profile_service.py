"""
backend/services/profile/profile_service.py
Persists candidate profile to storage/profile.json.
"""
import json
from pathlib import Path

_PROFILE_PATH = Path("storage/profile.json")
_PROFILE_PATH.parent.mkdir(exist_ok=True)


def load_profile() -> dict:
    if _PROFILE_PATH.exists():
        try:
            return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_profile(data: dict) -> dict:
    _PROFILE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data
