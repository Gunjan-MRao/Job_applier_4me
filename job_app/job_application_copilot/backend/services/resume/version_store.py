import json
import os
from collections import defaultdict

DATA_DIR = "data"
STORE_PATH = os.path.join(DATA_DIR, "resume_versions.json")

_VERSION_STORE: dict[str, list[dict]] = defaultdict(list)
_VERSION_INDEX: dict[str, dict] = {}


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_store() -> None:
    global _VERSION_STORE, _VERSION_INDEX

    _ensure_data_dir()

    if not os.path.exists(STORE_PATH):
        _VERSION_STORE = defaultdict(list)
        _VERSION_INDEX = {}
        return

    with open(STORE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    restored = defaultdict(list)
    restored.update(raw.get("by_email", {}))
    _VERSION_STORE = restored
    _VERSION_INDEX = raw.get("by_id", {})


def _save_store() -> None:
    _ensure_data_dir()

    payload = {
        "by_email": dict(_VERSION_STORE),
        "by_id": _VERSION_INDEX,
    }

    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def save_resume_version(candidate_email: str, record: dict) -> None:
    email_key = candidate_email.lower()
    _VERSION_STORE[email_key].append(record)
    _VERSION_INDEX[record["version_id"]] = record
    _save_store()


def list_resume_versions(candidate_email: str) -> list[dict]:
    email_key = candidate_email.lower()
    return list(_VERSION_STORE.get(email_key, []))


def get_resume_version_by_id(version_id: str) -> dict | None:
    return _VERSION_INDEX.get(version_id)


def clear_resume_versions() -> None:
    global _VERSION_STORE, _VERSION_INDEX
    _VERSION_STORE = defaultdict(list)
    _VERSION_INDEX = {}
    _save_store()


_load_store()