import json
import os
from collections import defaultdict

DATA_DIR = "data"
STORE_PATH = os.path.join(DATA_DIR, "applications.json")

_APPLICATION_STORE: dict[str, list[dict]] = defaultdict(list)
_APPLICATION_INDEX: dict[str, dict] = {}


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_store() -> None:
    global _APPLICATION_STORE, _APPLICATION_INDEX
    _ensure_data_dir()

    if not os.path.exists(STORE_PATH):
        _APPLICATION_STORE = defaultdict(list)
        _APPLICATION_INDEX = {}
        return

    with open(STORE_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)

    restored = defaultdict(list)
    restored.update(raw.get("by_email", {}))
    _APPLICATION_STORE = restored
    _APPLICATION_INDEX = raw.get("by_id", {})


def _save_store() -> None:
    _ensure_data_dir()
    payload = {
        "by_email": dict(_APPLICATION_STORE),
        "by_id": _APPLICATION_INDEX,
    }
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def save_application(candidate_email: str, record: dict) -> None:
    email_key = candidate_email.lower()
    _APPLICATION_STORE[email_key].append(record)
    _APPLICATION_INDEX[record["application_id"]] = record
    _save_store()


def list_applications(candidate_email: str) -> list[dict]:
    email_key = candidate_email.lower()
    return list(_APPLICATION_STORE.get(email_key, []))


def get_application_by_id(application_id: str) -> dict | None:
    return _APPLICATION_INDEX.get(application_id)


def update_application_record(application_id: str, updated: dict) -> None:
    global _APPLICATION_STORE, _APPLICATION_INDEX

    existing = _APPLICATION_INDEX.get(application_id)
    if not existing:
        return

    candidate_email = existing["candidate_email"].lower()
    _APPLICATION_INDEX[application_id] = updated

    apps = _APPLICATION_STORE.get(candidate_email, [])
    for idx, rec in enumerate(apps):
        if rec["application_id"] == application_id:
            apps[idx] = updated
            break

    _APPLICATION_STORE[candidate_email] = apps
    _save_store()


def clear_applications() -> None:
    global _APPLICATION_STORE, _APPLICATION_INDEX
    _APPLICATION_STORE = defaultdict(list)
    _APPLICATION_INDEX = {}
    _save_store()


_load_store()