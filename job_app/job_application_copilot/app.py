"""
Job Application Copilot — Streamlit frontend v9.12

v9.12 — Root-cause fix for page-reset loop

The real bug (present in all previous versions):
  1. `<meta http-equiv="refresh">` fires a NEW browser HTTP request.
     Streamlit treats it as a fresh page load and re-runs the entire script.
     Any widget (file_uploader, button, radio) has its value reset to None / False
     by the browser, so the app falls back to the default page (Setup).
  2. Setting session_state["page"] inside a function that runs AFTER widgets are
     drawn is ignored or overwritten by Streamlit's widget reconciliation.

Fix — three interlocking changes:
  A. Replace <meta refresh> with streamlit_autorefresh (JS-side polling that does
     NOT trigger a full browser reload — it calls Streamlit's internal rerun RPC).
     Falls back to a 5-second st.rerun() sleep loop if the package is absent.
  B. Add a HARD PAGE-LOCK at the very top of main(), before any widget is drawn.
     If agent_launched is True, page is forced to PAGE_AGENT unconditionally.
     No widget can override this because it runs before any widget is instantiated.
  C. Use a proper state-machine: the only place that ever writes session_state["page"]
     is the top-level guard and explicit user button clicks — never inside a tab
     function that might be called on an unrelated rerun.
"""
import asyncio
import os
import re
import signal
import socket
import subprocess
import sys
import time
import threading
from collections import Counter
from io import BytesIO
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Optional autorefresh (replaces <meta> tag — does NOT reset browser state)
# ---------------------------------------------------------------------------
try:
    from streamlit_autorefresh import st_autorefresh  # pip install streamlit-autorefresh
    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False

# ---------------------------------------------------------------------------
# Secrets → environment (Streamlit Community Cloud compatibility)
# ---------------------------------------------------------------------------
# On Streamlit Cloud there is no .env file; secrets are provided via st.secrets
# (App settings → Secrets). backend.core.config reads os.environ at IMPORT time,
# so we must copy any st.secrets values into os.environ BEFORE any backend module
# is imported. Existing os.environ / .env values always win so local runs are
# unchanged. This is a no-op when no secrets file is configured.
_SECRET_KEYS = [
    "GROQ_API_KEY", "GEMINI_API_KEY",
    "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY",
    "EMAIL_ADDRESS", "EMAIL_PASSWORD",
]


def _load_secrets_into_env() -> None:
    try:
        secrets = st.secrets  # raises/empty if no secrets.toml is present
    except Exception:
        return
    for key in _SECRET_KEYS:
        if os.environ.get(key):
            continue  # never override an explicit env var / .env value
        try:
            val = secrets[key]
        except Exception:
            continue
        if val:
            os.environ[key] = str(val)


# NOTE: _load_secrets_into_env() is invoked at the top of main(), right after
# st.set_page_config — accessing st.secrets counts as a Streamlit command, so it
# must not run at import time (that would make set_page_config no longer the
# first command). It still runs before any backend module is imported, because
# all backend imports in this file are lazy (inside functions).

# ---------------------------------------------------------------------------
# Run mode: embedded (in-process) vs http (talk to a running FastAPI backend)
# ---------------------------------------------------------------------------
# Streamlit Community Cloud runs ONE process (`streamlit run app.py`) — it cannot
# also run uvicorn. In embedded mode the UI calls the pipeline logic directly as
# in-process function calls (no HTTP), so it needs no backend server. Local
# launch_app.bat / launch.py can still run the FastAPI backend and set
# RUN_MODE=http to use the HTTP path, which is left fully intact.
EMBEDDED = os.environ.get("RUN_MODE", "embedded").strip().lower() != "http"

BASE_DIR     = Path(__file__).resolve().parent
API_HOST     = "127.0.0.1"
API_PORT     = 8000
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
PID_FILE     = BASE_DIR / "runtime_api.pid"
LOG_FILE     = BASE_DIR / "backend_startup.log"
PYTHON_EXE   = sys.executable

PAGE_SETUP  = "setup"
PAGE_AGENT  = "agent"
PAGE_DEBATE = "debate"
PAGE_APPS   = "apps"
PAGE_HEALTH = "health"

PAGE_LABELS = {
    PAGE_SETUP:  "\u2699\ufe0f Setup",
    PAGE_AGENT:  "\U0001f916 AI Agent",
    PAGE_DEBATE: "\U0001f9e0 Agent Debate",
    PAGE_APPS:   "\U0001f4cb Applications",
    PAGE_HEALTH: "\U0001fa7a Health",
}
PAGES = [PAGE_SETUP, PAGE_AGENT, PAGE_DEBATE, PAGE_APPS, PAGE_HEALTH]

SOURCE_ICONS = {
    "linkedin":           "\U0001f535 LinkedIn",
    "indeed":             "\U0001f50d Indeed",
    "glassdoor":          "\U0001f3e2 Glassdoor",
    "google":             "\U0001f50e Google Jobs",
    "reed":               "\U0001f4d5 Reed",
    "cvlibrary":          "\U0001f4da CV-Library",
    "totaljobs":          "\U0001f4bc TotalJobs",
    "findajob":           "\U0001f3f7\ufe0f Find a Job (GOV.UK)",
    "nhs":                "\U0001f3e5 NHS Jobs",
    "ukvisasponsorships": "\U0001f6e3\ufe0f UK Visa Sponsorships",
    "fallback":           "\U0001f4e6 Sample",
}

# No resume parsed yet → keep the keyword box empty and let the placeholder
# prompt the user. This is deliberately NOT a specific persona/industry; real
# keywords always come from the parsed resume (see smart_keywords) or user input.
DEFAULT_KEYWORDS = ""
KEYWORDS_PLACEHOLDER = "e.g. the job titles you want, comma-separated"

POLL_THROTTLE_S  = 4.0
AUTO_REFRESH_MS  = 5000  # for st_autorefresh

# Plain-string constants for characters used INSIDE f-string {expression} parts.
# A backslash escape (e.g. a "—" em-dash) placed directly inside f-string braces
# is a SyntaxError on Python < 3.12 (PEP 701 only relaxed this in 3.12). Keeping
# them as module constants makes every f-string below work on Python 3.9+.
EM_DASH    = "\u2014"                # em-dash placeholder for a missing value
ICON_WARN  = "\u26a0\ufe0f"        # warning sign
ICON_CHECK = "\u2705"                # check mark

# Job-source API keys that unlock LIVE data. Missing ALL of these is why the
# pipeline falls back to built-in sample listings.
_JOB_SOURCE_KEYS = ["ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY"]


def _env_value(name: str) -> str:
    """Look a key up in os.environ, then st.secrets, then the local .env file."""
    val = os.environ.get(name, "")
    if val:
        return val
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith(f"{name}="):
                v = line.split("=", 1)[1].strip()
                if v:
                    return v
    return ""


def _missing_job_api_keys() -> list:
    """Return the job-source API keys that are NOT configured anywhere."""
    return [k for k in _JOB_SOURCE_KEYS if not _env_value(k)]


def _render_mock_banner() -> None:
    """Big, impossible-to-miss red banner shown whenever results are SAMPLE data.

    Never blend sample listings in silently. State plainly that these are not
    live openings and name the likely cause (missing API keys).
    """
    missing = _missing_job_api_keys()
    if missing:
        cause = (
            "No live job-search API keys are configured, so no live source could "
            f"be reached. Missing: **{', '.join(missing)}**."
        )
        fix = (
            "Add **ADZUNA_APP_ID** + **ADZUNA_APP_KEY** (and optionally "
            "**REED_API_KEY**) \u2014 via `.env` locally or **App settings \u2192 Secrets** "
            "on Streamlit Cloud \u2014 then run the agent again."
        )
    else:
        cause = (
            "The live job sources returned no results or could not be reached, "
            "so built-in sample listings are being shown instead."
        )
        fix = "Try different keywords/location, or run the agent again shortly."
    st.error(
        "\U0001f6a8 **SAMPLE DATA \u2014 these are NOT real job openings.**\n\n"
        f"{cause}\n\n{fix}"
    )


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

def _go(page: str):
    """Switch page and immediately rerun — the ONLY way to change pages."""
    st.session_state["page"] = page
    st.rerun()


def _render_nav():
    current = st.session_state["page"]
    cols = st.columns(len(PAGES))
    for col, pid in zip(cols, PAGES):
        label = PAGE_LABELS[pid]
        is_active = (current == pid)
        with col:
            if st.button(
                label,
                key=f"nav_{pid}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
                disabled=is_active,          # active tab cannot be re-clicked
            ):
                _go(pid)


# ---------------------------------------------------------------------------
# Backend process helpers
# ---------------------------------------------------------------------------

def is_port_open(host=API_HOST, port=API_PORT, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_pid():
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip()) if PID_FILE.exists() else None
    except Exception:
        return None


def process_alive(pid):
    if pid is None:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in r.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _preflight_backend_deps():
    """Return (ok, message). Checks the things that silently break startup."""
    import importlib.util
    missing = [m for m in ("uvicorn", "fastapi") if importlib.util.find_spec(m) is None]
    if missing:
        pkgs = " ".join(missing)
        return False, (
            f"Required package(s) not installed in this Python: {pkgs}.\n"
            f"Python in use: {PYTHON_EXE}\n"
            f"Fix: \"{PYTHON_EXE}\" -m pip install {pkgs}"
        )
    if not (BASE_DIR / "backend" / "main.py").exists():
        return False, (
            f"Cannot find backend/main.py under {BASE_DIR}.\n"
            "Run the launcher from inside the job_application_copilot/ folder."
        )
    return True, ""


def start_backend():
    if is_port_open():
        return True, "Backend already running."

    ok, msg = _preflight_backend_deps()
    if not ok:
        LOG_FILE.write_text(msg, encoding="utf-8")
        return False, msg

    LOG_FILE.write_text("", encoding="utf-8")
    cmd = [
        PYTHON_EXE, "-m", "uvicorn", "backend.main:app",
        "--host", API_HOST, "--port", str(API_PORT), "--log-level", "info",
    ]
    log_handle = None
    try:
        log_handle = open(LOG_FILE, "w")
        kw = dict(cwd=str(BASE_DIR), stdout=log_handle, stderr=subprocess.STDOUT)
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kw)
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        for _ in range(30):
            if is_port_open():
                return True, f"Backend started (PID {proc.pid})"
            # If the child already exited, don't wait the full 15s — surface the error now.
            if proc.poll() is not None:
                log = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-1500:] if LOG_FILE.exists() else ""
                hint = ""
                if "Address already in use" in log or "10048" in log:
                    hint = (f"\n\nHint: port {API_PORT} is already in use by another process. "
                            f"Close whatever is using it, or stop the old backend, then retry.")
                elif "ModuleNotFoundError" in log or "ImportError" in log:
                    hint = ("\n\nHint: a Python package is missing in this environment. "
                            f"Run: \"{PYTHON_EXE}\" -m pip install -r requirements.txt")
                return False, (
                    f"Backend process exited immediately (code {proc.returncode}).{hint}\n\n"
                    f"Startup log:\n{log}"
                )
            time.sleep(0.5)
        log = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-1500:] if LOG_FILE.exists() else ""
        return False, (
            f"Backend did not open port {API_PORT} within 15s.\n\n"
            f"Startup log:\n{log or '(empty — check that uvicorn is installed)'}"
        )
    except Exception as exc:
        return False, f"Could not launch backend: {exc}\nPython in use: {PYTHON_EXE}"
    finally:
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass


def stop_backend():
    pid = read_pid()
    if not is_port_open() and not process_alive(pid):
        if PID_FILE.exists():
            PID_FILE.unlink()
        return True, "Already stopped."
    if pid and process_alive(pid):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    if PID_FILE.exists():
        PID_FILE.unlink()
    for _ in range(10):
        if not is_port_open():
            return True, "Backend stopped."
        time.sleep(0.5)
    return True, "Stop signal sent."


def backend_status_info():
    if EMBEDDED:
        return "Embedded", "Running in-process (no separate backend server needed)"
    pid = read_pid()
    if is_port_open():
        label, detail = "Running", f"Listening on {API_BASE_URL}"
        if pid and process_alive(pid):
            detail += f" (PID {pid})"
        return label, detail
    if pid and process_alive(pid):
        return "Starting", f"Process {pid} alive, port not open yet"
    if PID_FILE.exists():
        PID_FILE.unlink()
    return "Stopped", "Not running"


# ---------------------------------------------------------------------------
# Backend readiness (mode-aware)
# ---------------------------------------------------------------------------

def _backend_ready() -> bool:
    """True when the pipeline can be reached — always True in embedded mode
    (in-process), else a live HTTP backend must be listening."""
    return EMBEDDED or is_port_open()


# ---------------------------------------------------------------------------
# API client — embedded (in-process) OR HTTP, same (data, err) contract
# ---------------------------------------------------------------------------
# In embedded mode we call the SAME functions the FastAPI routes call, so both
# entry points share one code path. Payload/response shapes are identical to the
# HTTP JSON, so every call site below is mode-agnostic.

def _embedded_get(path):
    from backend.schemas.automation import AutomationStatusResponse
    from backend.services.automation_runtime import get_run
    if path.startswith("/automation/status/"):
        run_id = path.rsplit("/", 1)[-1].split("?", 1)[0]
        run = get_run(run_id)
        if not run:
            return None, "Run not found"
        return AutomationStatusResponse(**run).model_dump(), None
    if path.startswith("/applications/"):
        from backend.services.application.application_service import (
            get_applications_for_candidate,
        )
        email = path.rsplit("/", 1)[-1].split("?", 1)[0]
        import urllib.parse
        return get_applications_for_candidate(urllib.parse.unquote(email)), None
    return None, f"embedded: unsupported GET {path}"


def _embedded_post(path, payload):
    if path == "/automation/start":
        from backend.schemas.automation import AutomationStartPayload
        from backend.services.automation_runtime import start_run_thread
        run = start_run_thread(AutomationStartPayload(**payload))
        return {"run_id": run["run_id"], "status": run["status"],
                "message": "Automation run started successfully."}, None
    return None, f"embedded: unsupported POST {path}"


def _embedded_patch(path, payload):
    # /applications/{application_id}/status
    if path.startswith("/applications/") and path.endswith("/status"):
        from backend.services.application.application_service import (
            update_application_status,
        )
        app_id = path[len("/applications/"):-len("/status")]
        try:
            result = update_application_status(
                application_id=app_id,
                new_status=payload.get("status"),
                notes=payload.get("notes"),
            )
        except ValueError as exc:
            return None, str(exc)
        return result, None
    return None, f"embedded: unsupported PATCH {path}"


# ---------------------------------------------------------------------------
# HTTP helpers (used directly in http mode; embedded mode short-circuits above)
# ---------------------------------------------------------------------------

def _get(path, timeout=10):
    if EMBEDDED:
        try:
            return _embedded_get(path)
        except Exception as e:
            return None, str(e)
    try:
        r = requests.get(f"{API_BASE_URL}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _post(path, payload, timeout=60):
    if EMBEDDED:
        try:
            return _embedded_post(path, payload)
        except Exception as e:
            return None, str(e)
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _patch(path, payload, timeout=10):
    if EMBEDDED:
        try:
            return _embedded_patch(path, payload)
        except Exception as e:
            return None, str(e)
    try:
        r = requests.patch(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------

def _extract_text_raw(file_bytes, suffix):
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            from io import BytesIO as _BytesIO
            reader = PdfReader(_BytesIO(file_bytes))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pages.append("")
            return "\n".join(pages)
        if suffix == ".docx":
            from docx import Document
            return "\n".join(p.text for p in Document(BytesIO(file_bytes)).paragraphs)
    except Exception:
        pass
    return ""


def _minimal_parse(filename, text):
    em = re.search(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", text, re.I)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    skills_kw = [
        "supply chain", "logistics", "procurement", "sap", "excel",
        "operations", "forecasting", "power bi", "inventory management",
        "demand planning", "erp", "sql", "python",
    ]
    stem = Path(filename).stem if filename else ""
    stem = re.sub(r"[_\-]?(resume|cv|updated|new|final|\d{4})", "", stem, flags=re.I)
    stem = stem.replace("_", " ").replace("-", " ").strip()
    name = stem.title() if stem else (lines[0][:60] if lines else None)
    return {
        "filename": filename,
        "candidate_name": name,
        "email": em.group(0) if em else None,
        "phone": None,
        "skills": [s for s in skills_kw if s in text.lower()],
        "likely_roles": [],
        "education": [],
        "years_of_experience_hint": None,
        "preview": " ".join(text.split())[:600],
    }


def parse_resume_local(file_bytes, filename):
    import tempfile
    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        from backend.services.parser.resume_parser import build_profile_preview, extract_resume_text
        return build_profile_preview(filename, extract_resume_text(tmp_path)), None
    except Exception:
        text = _extract_text_raw(file_bytes, suffix)
        return _minimal_parse(filename, text), None
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


def parse_resume(file_bytes, filename):
    # Embedded mode parses in-process (no server). HTTP mode tries the backend
    # first, falling back to the same local parser if it is unreachable.
    if not EMBEDDED and is_port_open():
        try:
            r = requests.post(
                f"{API_BASE_URL}/resume/parse",
                files={"file": (filename, file_bytes, "application/octet-stream")},
                timeout=30,
            )
            r.raise_for_status()
            return r.json(), None
        except Exception:
            pass
    return parse_resume_local(file_bytes, filename)


def smart_keywords(profile: dict) -> str:
    """Derive search keywords from the ACTUAL parsed resume — the candidate's
    detected job titles first, then their skills. There is deliberately NO
    hardcoded industry/persona fallback: whatever the resume contains is what
    drives the search, so a software CV yields software keywords, a finance CV
    finance keywords, etc. If the resume has no detectable roles or skills we
    return an empty string and let the user type keywords manually.
    """
    roles  = profile.get("likely_roles") or []
    skills = profile.get("skills") or []
    combined = list(roles[:3]) + list(skills[:6])
    seen, out = set(), []
    for k in combined:
        k = (k or "").strip()
        kl = k.lower()
        if k and kl not in seen:
            seen.add(kl)
            out.append(k)
    return ", ".join(out[:8])


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def status_pill(s, custom_color=None):
    c = custom_color or {
        "running": "#0ea5e9", "completed": "#10b981", "failed": "#ef4444",
        "queued":  "#f59e0b", "starting":  "#f59e0b", "stopped": "#6b7280",
        "draft":   "#f59e0b", "submitted": "#10b981", "rejected": "#ef4444",
        "interview": "#8b5cf6", "needs review": "#f97316",
    }.get((s or "").lower(), "#6b7280")
    return (
        f'<span style="padding:3px 12px;border-radius:999px;background:{c}22;'
        f'color:{c};font-weight:700;font-size:13px;border:1px solid {c}66">{s}</span>'
    )


def source_label(s):
    return SOURCE_ICONS.get((s or "").lower(), f"\U0001f50d {s}")


def _sidebar_name(p, filename):
    name = (p or {}).get("candidate_name") or ""
    if not name and filename:
        stem = Path(filename).stem
        stem = re.sub(r"[_\-]?(resume|cv|updated|new|final|\d{4})", "", stem, flags=re.I)
        name = stem.replace("_", " ").replace("-", " ").strip().title()
    return name or "?"


# ---------------------------------------------------------------------------
# Agent background thread
# ---------------------------------------------------------------------------

def _get_pending() -> dict:
    if "_pending" not in st.session_state:
        st.session_state["_pending"] = {"done": False, "run_id": None, "error": None, "stage": ""}
    return st.session_state["_pending"]


def _reset_pending():
    st.session_state["_pending"] = {"done": False, "run_id": None, "error": None, "stage": ""}


def _launch_agent_thread(pending: dict):
    # Embedded mode runs the pipeline in-process \u2014 no backend server to start.
    if not EMBEDDED:
        pending["stage"] = "\u2699\ufe0f Starting backend..."
        if not is_port_open():
            ok, msg = start_backend()
            if not ok:
                pending["error"] = f"Backend failed to start: {msg}"
                pending["done"]  = True
                return
    pending["stage"] = "\U0001f4e1 Starting automation run..."
    cfg = pending.get("cfg", {})
    result, err = _post("/automation/start", cfg)
    if err or not result:
        pending["error"] = f"API error: {err}"
        pending["done"]  = True
        return
    pending["run_id"] = result.get("run_id", "")
    pending["done"]   = True


# ---------------------------------------------------------------------------
# Polling — throttled, no meta-refresh
# ---------------------------------------------------------------------------

def _poll_status(run_id: str) -> dict:
    now     = time.monotonic()
    last_ts = st.session_state.get("_last_poll_ts", 0.0)
    cached  = st.session_state.get("_last_poll_data")
    if cached is not None and (now - last_ts) < POLL_THROTTLE_S:
        return cached
    data, err = _get(f"/automation/status/{run_id}", timeout=8)
    if err or not data:
        return {"status": "unknown", "stage": f"Poll error: {err}"}
    st.session_state["_last_poll_ts"]   = now
    st.session_state["_last_poll_data"] = data
    return data


def _trigger_autorefresh():
    """Safe polling rerun — uses st_autorefresh if available, else a
    main-thread sleep+rerun.

    NEVER spawn a background thread that calls st.rerun()/st.session_state:
    a non-script thread runs OUTSIDE Streamlit's ScriptRunContext, so those
    calls are silently dropped (the "missing ScriptRunContext" warning) and
    the UI freezes after "Start AI Agent" even though the backend is working.
    The fallback below sleeps and reruns on the MAIN script thread, which has
    the context, so the rerun actually happens.
    """
    if _HAS_AUTOREFRESH:
        st_autorefresh(interval=AUTO_REFRESH_MS, key="agent_refresh")
    else:
        time.sleep(AUTO_REFRESH_MS / 1000.0)
        st.rerun()


# ---------------------------------------------------------------------------
# Page: Setup
# ---------------------------------------------------------------------------

def tab_setup():
    st.subheader("\u2699\ufe0f Upload your resume")
    st.write("\U0001f4a1 Parsing works **immediately** \u2014 no need to start the backend first.")

    uploaded = st.file_uploader("Choose your CV (PDF or DOCX)", type=["pdf", "docx"],
                                key="cv_uploader")
    if uploaded is not None:
        # Store raw bytes in session so we survive reruns without re-uploading
        st.session_state["_upload_bytes"]    = uploaded.read()
        st.session_state["_upload_filename"] = uploaded.name

    fb       = st.session_state.get("_upload_bytes")
    fname    = st.session_state.get("_upload_filename", "")

    if fb:
        st.info(f"Selected: **{fname}** ({len(fb):,} bytes)")
        if st.button("Parse resume \u27a4", type="primary", key="btn_parse"):
            with st.spinner("Parsing..."):
                profile, err = parse_resume(fb, fname)
            if err:
                st.error(err)
            else:
                st.session_state["resume_profile"]  = profile
                st.session_state["resume_filename"] = fname
                if profile.get("email") and not st.session_state.get("candidate_email"):
                    st.session_state["candidate_email"] = profile["email"]
                # Stay on Setup so the user can REVIEW the parsed profile below.
                # Advancing to the AI Agent step is an explicit user action via the
                # "Go to AI Agent" button — never an automatic jump on parse.
                st.rerun()

    p = st.session_state.get("resume_profile")
    if p:
        st.success("✅ Resume parsed — review the details below, then click **Go to AI Agent** when ready.")
        st.markdown("### \U0001f4cc Extracted profile")
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"\U0001f464 **Name:** {p.get('candidate_name') or EM_DASH}")
            st.write(f"\U0001f4e7 **Email:** {p.get('email') or EM_DASH}")
            st.write(f"\U0001f4bc **Experience:** {p.get('years_of_experience_hint') or EM_DASH}")
        with c2:
            roles_str   = ", ".join(p.get("likely_roles") or []) or "\u2014"
            skills_list = p.get("skills") or []
            st.write(f"\U0001f3af **Roles detected:** {roles_str}")
            st.write(f"\u2699\ufe0f **Skills ({len(skills_list)}):** {', '.join(skills_list) or EM_DASH}")
        edu_list = p.get("education") or []
        if edu_list:
            st.write(f"\U0001f393 **Education:** {', '.join(edu_list)}")
        st.info(f"\U0001f511 **Keywords for agent:** `{smart_keywords(p)}`")
        with st.expander("Resume text preview"):
            st.text(p.get("preview", ""))
        if st.button("\U0001f916 Go to AI Agent \u27a4", type="primary", key="btn_goto_agent"):
            _go(PAGE_AGENT)


# ---------------------------------------------------------------------------
# Page: AI Agent
# ---------------------------------------------------------------------------

def tab_agent():
    st.subheader("\U0001f916 AI Job Agent")
    p = st.session_state.get("resume_profile") or {}

    # ---- Backend + Gemini status row ----
    col_be, col_gem = st.columns(2)
    be_status, _ = backend_status_info()
    with col_be:
        if be_status == "Embedded":
            st.info("\U0001f7e2 Backend: **Embedded (in-process)**")
        elif be_status == "Running":
            st.info("\U0001f7e2 Backend: **Running**")
        else:
            st.warning(f"\U0001f534 Backend: **{be_status}** \u2014 agent will start it automatically")

    def _env_key(*names: str) -> str:
        for name in names:
            val = os.environ.get(name, "")
            if val:
                return val
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                for name in names:
                    if line.strip().startswith(f"{name}="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
        return ""

    llm_key      = _env_key("GROQ_API_KEY", "GEMINI_API_KEY")
    llm_provider = "Groq" if _env_key("GROQ_API_KEY") else "Gemini"
    with col_gem:
        if llm_key:
            st.success(f"\u2705 {llm_provider} API key \u2014 AI cover letters enabled")
        else:
            st.warning("\u26a0\ufe0f No LLM key \u2014 using smart offline templates (add GROQ_API_KEY for AI)")

    if not p:
        st.warning("\u26a0\ufe0f No resume loaded \u2014 go to **\u2699\ufe0f Setup** first for best results.")

    # ---- Launch form (only shown when agent is NOT yet running) ----
    if not st.session_state.get("agent_launched"):
        default_kw = smart_keywords(p) if p else DEFAULT_KEYWORDS
        with st.form("agent_form"):
            c1, c2   = st.columns(2)
            keywords = c1.text_input("\U0001f511 Keywords", value=default_kw)
            location = c2.text_input("\U0001f4cd Location", "United Kingdom")
            with st.expander("\U0001f527 Advanced filters (optional)"):
                blacklist  = st.text_input("Skip these companies (comma-separated)", "")
                whitelist  = st.text_input("Only show these companies (optional)", "")
                auto_apply = st.checkbox("Auto-generate cover letter + cold email per match", value=True)
            go = st.form_submit_button(
                "\U0001f680 Start AI Agent \u2014 scan ALL job boards",
                type="primary", use_container_width=True,
            )

        if go:
            cfg = {
                "candidate_email":   st.session_state.get("candidate_email") or "user@example.com",
                "keywords":          [x.strip() for x in keywords.split(",") if x.strip()],
                "location":          location,
                "auto_apply":        auto_apply,
                "track_live":        True,
                "resume_filename":   st.session_state.get("resume_filename") or None,
                "resume_profile":    p or None,
                "company_blacklist": [x.strip() for x in blacklist.split(",") if x.strip()],
                "company_whitelist": [x.strip() for x in whitelist.split(",") if x.strip()],
            }
            # Persist everything BEFORE rerun
            st.session_state["agent_launched"] = True
            st.session_state["page"]           = PAGE_AGENT
            st.session_state["run_id"]         = None
            st.session_state["agent_status"]   = "starting"
            st.session_state["agent_stage"]    = "\u2699\ufe0f Connecting to backend..."
            st.session_state["agent_cfg"]      = cfg
            st.session_state.pop("_last_poll_ts",   None)
            st.session_state.pop("_last_poll_data", None)
            _reset_pending()
            pending = _get_pending()
            pending["cfg"] = cfg
            threading.Thread(target=_launch_agent_thread, args=(pending,), daemon=True).start()
            st.rerun()
        else:
            st.markdown("---")
            st.info(
                "\U0001f446 Fill in your keywords above and click **\U0001f680 Start AI Agent** to begin.\n\n"
                "The agent simultaneously searches **LinkedIn, Indeed, Glassdoor, Reed, "
                "CV-Library, TotalJobs, GOV.UK Find a Job, NHS Jobs, and UK Visa Sponsorships** \u2014 "
                "then instantly generates a tailored cover letter and cold recruiter email for every match."
            )
        return  # nothing more to show until agent launches

    # ---- Agent is running — dashboard ----
    st.markdown("---")
    pending = _get_pending()
    if pending["done"] and not st.session_state.get("run_id"):
        if pending.get("error"):
            st.session_state["agent_status"] = "failed"
            st.session_state["agent_stage"]  = pending["error"]
        elif pending.get("run_id"):
            st.session_state["run_id"]       = pending["run_id"]
            st.session_state["agent_status"] = "running"
            st.session_state["agent_stage"]  = "\U0001f50d Scanning job boards..."

    if not st.session_state.get("run_id") and st.session_state.get("agent_status") != "failed":
        stage = pending.get("stage") or st.session_state.get("agent_stage") or "Starting..."
        st.info(f"\u23f3 {stage}")
        _trigger_autorefresh()
        return

    run_id = st.session_state.get("run_id", "")
    if run_id:
        data          = _poll_status(run_id)
        applied_jobs  = data.get("applied_jobs") or []
        source_counts = dict(Counter(j.get("source", "unknown") for j in applied_jobs))
        st.session_state["agent_status"]   = data.get("status", "unknown")
        st.session_state["agent_stage"]    = data.get("stage", "")
        st.session_state["agent_progress"] = data.get("progress_percent", 0)
        st.session_state["agent_scanned"]  = data.get("jobs_scanned", 0)
        st.session_state["agent_matched"]  = data.get("jobs_matched", 0)
        st.session_state["agent_applied"]  = data.get("jobs_applied", 0)
        st.session_state["agent_url"]      = data.get("current_url") or ""
        st.session_state["agent_matches"]  = data.get("top_matches") or []
        st.session_state["agent_jobs"]     = applied_jobs
        st.session_state["agent_sources"]  = source_counts
        st.session_state["agent_summary"]  = data.get("result_summary")
        st.session_state["agent_used_mock"]   = bool(data.get("used_mock"))
        st.session_state["agent_source_used"] = data.get("source_used")

    status        = st.session_state.get("agent_status", "unknown")
    stage         = st.session_state.get("agent_stage", "")
    prog          = st.session_state.get("agent_progress", 0)
    scanned       = st.session_state.get("agent_scanned", 0)
    matched       = st.session_state.get("agent_matched", 0)
    applied_count = st.session_state.get("agent_applied", 0)
    current_url   = st.session_state.get("agent_url", "")
    source_counts = st.session_state.get("agent_sources", {})
    aj            = st.session_state.get("agent_jobs", [])
    summary       = st.session_state.get("agent_summary")
    running       = status not in ("completed", "failed", "unknown")

    r1c1, r1c2 = st.columns([1, 3])
    r1c1.markdown(f"**Status:** {status_pill(status)}", unsafe_allow_html=True)
    if stage:
        r1c2.info(f"\U0001f4cd {stage}")
    st.progress(min(max(int(prog), 0), 100))
    if current_url and running:
        st.caption(f"\u23f3 Scanning: {current_url[:90]}")

    # ---- Honest mock-data banner ----------------------------------------
    # When the pipeline could not reach a live job source it falls back to
    # built-in SAMPLE listings. Never blend those in silently: show a big,
    # impossible-to-miss red banner naming the likely cause so the user knows
    # these are NOT real job openings.
    if st.session_state.get("agent_used_mock") and not running:
        _render_mock_banner()

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("\U0001f50d Jobs Found",   scanned)
    mc2.metric("\u2705 Matched",           matched)
    mc3.metric("\U0001f4e4 Applications", applied_count)
    mc4.metric("\u26a0\ufe0f Needs Review",
               sum(1 for j in aj if not j.get("cover_letter")))

    st.markdown("#### \U0001f4f6 Live source feed")
    source_cols = st.columns(len(SOURCE_ICONS))
    for i, (src, icon) in enumerate(SOURCE_ICONS.items()):
        cnt = source_counts.get(src, 0)
        with source_cols[i]:
            if cnt > 0:
                st.success(f"{icon}\n\n**{cnt}**")
            elif running:
                st.info(f"{icon}\n\n*...*")
            else:
                st.caption(icon)

    st.markdown("---")
    needs_review = [j for j in aj if not j.get("cover_letter")]
    ready        = [j for j in aj if  j.get("cover_letter")]
    if needs_review:
        st.markdown(f"### \u26a0\ufe0f Needs Your Review ({len(needs_review)})")
        st.caption("Matched but cover letter couldn\u2019t be generated \u2014 apply manually.")
        for job in reversed(needs_review[-20:]):
            _render_job_card(job, review_mode=True)
    if ready:
        st.markdown(f"### \U0001f4e8 Ready to Send ({len(ready)})")
        for job in reversed(ready[-50:]):
            _render_job_card(job, review_mode=False)

    log = st.session_state.get("agent_log", [])
    with st.expander("\U0001f4dd Agent log", expanded=running):
        if log:
            for line in reversed(log[-60:]):
                st.code(line, language=None)
        else:
            st.caption("Log will appear here once the agent starts sending results.")

    if summary:
        with st.expander("\U0001f4c8 Final summary"):
            st.json(summary)

    if running:
        _trigger_autorefresh()
    elif status == "completed":
        st.balloons()
        if st.button("\U0001f504 Start a new search", key="btn_new_search"):
            for k in ("agent_launched", "run_id", "agent_status", "agent_stage",
                      "agent_progress", "agent_scanned", "agent_matched",
                      "agent_applied", "agent_url", "agent_jobs", "agent_sources",
                      "agent_summary", "agent_matches", "agent_log", "agent_cfg",
                      "_last_poll_ts", "_last_poll_data", "_pending"):
                st.session_state.pop(k, None)
            _go(PAGE_SETUP)
    elif status == "failed":
        st.error(f"\u274c Agent failed: {stage}")
        if st.button("\U0001f504 Try again", key="btn_try_again"):
            for k in ("agent_launched", "run_id", "agent_status", "agent_stage",
                      "agent_progress", "agent_scanned", "agent_matched",
                      "agent_applied", "agent_url", "agent_jobs", "agent_sources",
                      "agent_summary", "agent_matches", "agent_log", "agent_cfg",
                      "_last_poll_ts", "_last_poll_data", "_pending"):
                st.session_state.pop(k, None)
            _go(PAGE_AGENT)


def _sponsorship_badge(job: dict) -> str:
    """Badge HTML that keeps the authoritative GOV.UK-register signal visibly
    distinct from a weak, unverified JD-text mention. Falls back to the legacy
    sponsorship_status pill for jobs produced before sponsor_tier existed."""
    tier = job.get("sponsor_tier")
    if tier == "verified":
        return status_pill("\u2705 Sponsor-Verified (GOV.UK register)", "#10b981")
    if tier == "mentioned":
        return status_pill("\u26a0\ufe0f Mentions sponsorship (unverified)", "#f59e0b")
    if tier == "none":
        return status_pill("No sponsorship", "#ef4444")
    if tier == "unknown":
        return status_pill("Sponsorship ?", "#6b7280")
    return {
        "yes":     status_pill("Sponsors visas", "#10b981"),
        "no":      status_pill("No sponsorship", "#ef4444"),
        "unknown": status_pill("Sponsorship ?",  "#f59e0b"),
    }.get(job.get("sponsorship_status", "unknown"), "")


@st.cache_data(show_spinner=False)
def _docx_bytes(text: str, title: str) -> bytes:
    from backend.pipeline.exporters import to_docx_bytes
    return to_docx_bytes(text, title)


@st.cache_data(show_spinner=False)
def _pdf_bytes(text: str, title: str) -> bytes:
    from backend.pipeline.exporters import to_pdf_bytes
    return to_pdf_bytes(text, title)


def _download_row(text: str, title: str, base_name: str, key: str) -> None:
    """One-click PDF + DOCX download buttons for a drafted document."""
    from backend.pipeline.exporters import safe_filename
    stem = safe_filename(base_name)
    dc1, dc2 = st.columns(2)
    try:
        with dc1:
            st.download_button(
                "\u2b07\ufe0f Download as PDF", data=_pdf_bytes(text, title),
                file_name=f"{stem}.pdf", mime="application/pdf",
                key=f"pdf_{key}", use_container_width=True,
            )
        with dc2:
            st.download_button(
                "\u2b07\ufe0f Download as DOCX", data=_docx_bytes(text, title),
                file_name=f"{stem}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"docx_{key}", use_container_width=True,
            )
    except Exception as exc:  # never let an export lib hiccup break the card
        st.caption(f"Export unavailable: {exc}")


def _lead_cache() -> dict:
    return st.session_state.setdefault("_lead_cache", {})


def _find_lead(company: str, job_title: str) -> dict:
    """Look up a recruiter contact in-process (works with no backend running).
    Returns the raw lead_finder dict; never fabricates a verified contact."""
    from backend.services.lead_finder import sync_find_recruiter_email
    return sync_find_recruiter_email(company=company, job_title=job_title)


def _render_recruiter_contact(job: dict, key: str) -> None:
    """Per-job 'Find recruiter contact' control + honest result display."""
    company = job.get("company", "")
    title   = job.get("title", "")
    if not company or company == "Unknown company":
        return
    cache = _lead_cache()
    st.markdown("\U0001f9d1\u200d\U0001f4bc **Recruiter contact**")
    if st.button("\U0001f50e Find recruiter contact", key=f"lead_btn_{key}"):
        with st.spinner(f"Searching for a contact at {company}..."):
            try:
                cache[company] = _find_lead(company, title)
            except Exception as exc:
                cache[company] = {"email": None, "strategy": "error", "error": str(exc)}
    result = cache.get(company)
    if result is None:
        st.caption("Click to search verified sources (Hunter.io / Apollo.io).")
        return
    email    = result.get("email")
    strategy = result.get("strategy", "")
    if email and strategy in ("hunter", "apollo"):
        st.success(f"\u2705 Verified contact ({strategy}): **{email}**")
    elif email and strategy == "heuristic":
        st.warning(
            f"\u26a0\ufe0f No verified contact found. Best-guess pattern "
            f"(UNVERIFIED \u2014 confirm before using): `{email}`"
        )
    else:
        st.info("\u2139\ufe0f No recruiter contact found for this company.")


def _render_job_card(job: dict, review_mode: bool):
    fit   = job.get("fit_score", 0)
    title = job.get("title", "Unknown role")
    co    = job.get("company", "Unknown company")
    src   = source_label(job.get("source", ""))
    url   = job.get("url", "")
    spons_html = _sponsorship_badge(job)
    card_key = f"{url}{title}{fit}"
    label = f"{ICON_WARN if review_mode else ICON_CHECK} {fit}% | {title} @ {co} | {src}"
    with st.expander(label):
        hc1, hc2, hc3 = st.columns([2, 1, 1])
        with hc1:
            st.markdown(f"**{title}** at **{co}**")
            if url:
                st.link_button("\U0001f517 Apply / View job", url, use_container_width=True)
        with hc2:
            st.markdown(spons_html, unsafe_allow_html=True)
        with hc3:
            st.metric("Fit score", f"{fit}%")
        _render_recruiter_contact(job, card_key)
        if job.get("cover_letter"):
            st.markdown("\U0001f4dd **Cover Letter** (edit before sending):")
            st.text_area("cover_letter", value=job["cover_letter"], height=230,
                         key=f"cl_{card_key}")
            _download_row(job["cover_letter"], f"Cover Letter \u2014 {title} @ {co}",
                          f"cover_letter_{co}_{title}", f"cl_{card_key}")
        elif review_mode:
            st.warning("Cover letter failed \u2014 apply directly via the link above.")
        if job.get("cold_email"):
            st.markdown("\U0001f4e7 **Cold Recruiter Email** (edit before sending):")
            st.text_area("cold_email", value=job["cold_email"], height=190,
                         key=f"ce_{card_key}")
            _download_row(job["cold_email"], f"Cold Email \u2014 {title} @ {co}",
                          f"cold_email_{co}_{title}", f"ce_{card_key}")
        if job.get("resume_guidance"):
            with st.expander("\U0001f4c4 Resume tailoring tips"):
                g = job["resume_guidance"]
                if isinstance(g, dict):
                    for k in (g.get("keyword_analysis") or {}).get("matched_keywords") or []:
                        st.write(f"\u2705 {k}")
                    for k in (g.get("keyword_analysis") or {}).get("missing_keywords") or []:
                        st.write(f"\u26a0\ufe0f Add to CV: {k}")
                    for line in g.get("summary_rewrite_guidance") or []:
                        st.write(f"\u2022 {line}")


# ---------------------------------------------------------------------------
# Page: Agent Debate
# ---------------------------------------------------------------------------

AGENT_PROVIDER_COLOURS = {
    "gemini":        ("#4285F4", "\U0001f535", "Gemini 1.5 Flash"),
    "huggingface":   ("#FF6B00", "\U0001f7e0", "Mistral-7B (HuggingFace)"),
    "openai":        ("#10a37f", "\U0001f7e2", "GPT-4o-mini"),
    "anthropic":     ("#6b46c1", "\U0001f7e3", "Claude Haiku"),
    "reddit_oracle": ("#FF4500", "\U0001f534", "Reddit Oracle (Rule-based)"),
}

TIER_STYLE = {
    "tier1": ("#10b981", "\U0001f3c6 Tier 1 \u2014 GOV.UK verified + actively sponsoring"),
    "tier2": ("#f59e0b", "\u2705 Tier 2 \u2014 GOV.UK verified sponsor licence"),
    "tier3": ("#ef4444", "\u26a0\ufe0f  Tier 3 \u2014 Not on GOV.UK register \u2014 HIGH RISK"),
}


def _import_strategy():
    try:
        from backend.services.sponsor_strategy import run_multi_agent_debate, hiring_window_score
        return run_multi_agent_debate, hiring_window_score
    except ImportError:
        app_dir = str(BASE_DIR)
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        try:
            from backend.services.sponsor_strategy import run_multi_agent_debate, hiring_window_score
            return run_multi_agent_debate, hiring_window_score
        except Exception:
            return None, None


def _confidence_bar(score, label=""):
    if score is None:
        return "<em style='color:#888'>No response</em>"
    color = "#10b981" if score >= 70 else ("#f59e0b" if score >= 40 else "#ef4444")
    pct   = max(0, min(100, score))
    return (
        f'<div style="margin:4px 0">{label}'
        f'<div style="background:#1e293b;border-radius:8px;height:10px;width:100%;margin-top:4px">'
        f'<div style="background:{color};width:{pct}%;height:10px;border-radius:8px;"></div></div>'
        f'<small style="color:{color};font-weight:700">{score}/100</small></div>'
    )


def tab_debate():
    st.subheader("\U0001f9e0 Multi-Agent Strategy Debate")
    st.caption(
        "Paste a job you\u2019re considering \u2014 5 AI agents debate whether you should apply, "
        "how to approach it, and what the risks are."
    )
    run_debate_fn, hiring_window_fn = _import_strategy()
    if hiring_window_fn:
        try:
            win = hiring_window_fn()
            wc  = "#10b981" if win["score"] >= 70 else ("#f59e0b" if win["score"] >= 40 else "#ef4444")
            st.markdown(
                f'<div style="padding:8px 16px;border-radius:8px;background:{wc}22;'
                f'border:1px solid {wc}66;margin-bottom:12px">\U0001f4c5 '
                f'<strong>Current hiring window ({win["month"]}):</strong> '
                f'<span style="color:{wc}">{win["advice"]}</span></div>',
                unsafe_allow_html=True)
        except Exception:
            pass
    if run_debate_fn is None:
        st.error("\u274c Could not import sponsor_strategy.py.")
        return
    profile = st.session_state.get("resume_profile") or {}
    if not profile:
        st.warning("\u26a0\ufe0f No resume loaded \u2014 upload in **\u2699\ufe0f Setup** for personalised opinions.")
        profile = {"candidate_name": "Candidate", "skills": [], "years_of_experience_hint": "graduate"}
    with st.form("debate_form"):
        c1, c2    = st.columns(2)
        job_title = c1.text_input("Job Title", placeholder="e.g. Supply Chain Analyst")
        company   = c2.text_input("Company",   placeholder="e.g. DHL")
        c3, c4    = st.columns(2)
        location  = c3.text_input("Location", value="United Kingdom")
        salary    = c4.text_input("Salary",   placeholder="e.g. \u00a335,000")
        spons_sel = st.selectbox(
            "Sponsorship status", ["unknown", "yes", "no"],
            format_func=lambda x: {
                "yes": "\u2705 Confirmed", "no": "\u274c Explicitly no", "unknown": "\u2753 Not mentioned"
            }[x])
        job_desc = st.text_area("Job description excerpt (optional)", height=100)
        source   = st.text_input("Source", value="linkedin")
        run_btn  = st.form_submit_button("\U0001f9e0 Run Agent Debate", type="primary", use_container_width=True)
    if run_btn:
        if not job_title or not company:
            st.warning("Please enter at least a Job Title and Company.")
        else:
            job = {
                "title": job_title.strip(), "company": company.strip(),
                "location": location.strip(), "salary": salary.strip(),
                "sponsorship_status": spons_sel, "description": job_desc.strip(),
                "source": source.strip(), "url": "",
            }
            with st.spinner("\U0001f9e0 Agents debating... (10\u201330s)"):
                try:
                    st.session_state["last_debate"] = run_debate_fn(job, profile)
                except Exception as exc:
                    st.error(f"Debate failed: {exc}")
                    st.session_state.pop("last_debate", None)
    result = st.session_state.get("last_debate")
    if not result:
        st.info("Fill in job details above and click **\U0001f9e0 Run Agent Debate**.")
        return
    tier           = result.get("company_tier", "tier3")
    tier_colour, tier_label = TIER_STYLE.get(tier, ("#6b7280", "Unknown tier"))
    govuk          = result.get("govuk_verified")
    govuk_html     = (
        '<span style="color:#10b981;font-weight:700">\u2705 GOV.UK Verified Sponsor</span>' if govuk is True
        else '<span style="color:#ef4444;font-weight:700">\u274c NOT on GOV.UK Register</span>' if govuk is False
        else '<span style="color:#f59e0b;font-weight:700">\u2753 register could not be checked</span>'
    )
    st.markdown(
        f'<div style="display:flex;gap:16px;align-items:center;padding:10px 16px;border-radius:8px;'
        f'background:{tier_colour}22;border:1px solid {tier_colour}55;margin-bottom:16px">'
        f'<span style="color:{tier_colour};font-weight:700">{tier_label}</span>'
        f' | {govuk_html}</div>', unsafe_allow_html=True)
    st.markdown("### \U0001f3af Final Verdict")
    consensus = result.get("consensus_confidence")
    synthesis = result.get("synthesis", "")
    with st.container(border=True):
        if consensus is not None:
            color   = "#10b981" if consensus >= 70 else ("#f59e0b" if consensus >= 40 else "#ef4444")
            verdict = "APPLY" if consensus >= 70 else "APPLY WITH CAUTION" if consensus >= 40 else "SKIP"
            st.markdown(
                f'<div style="text-align:center;padding:12px 0">'
                f'<span style="font-size:2rem;font-weight:900;color:{color}">{verdict}</span>'
                f'<br><span style="color:{color};font-size:18px">Consensus: {consensus}/100</span></div>',
                unsafe_allow_html=True)
            st.markdown(_confidence_bar(consensus, "Overall: "), unsafe_allow_html=True)
        if synthesis:
            st.markdown("---")
            st.markdown(synthesis)
    st.markdown("---")
    st.markdown("### \U0001f5e3\ufe0f Agent Opinions")
    for ar in (result.get("agents") or []):
        agent_id   = ar.get("agent", "unknown")
        name       = ar.get("name", agent_id)
        opinion    = ar.get("opinion") or "*(no response)*"
        confidence = ar.get("confidence")
        colour, emoji, provider_label = AGENT_PROVIDER_COLOURS.get(agent_id, ("#6b7280", "\u26aa", agent_id))
        with st.container(border=True):
            ci, cb = st.columns([1, 9])
            ci.markdown(f'<div style="font-size:2rem;text-align:center;padding-top:8px">{emoji}</div>',
                        unsafe_allow_html=True)
            with cb:
                st.markdown(f'<span style="color:{colour};font-weight:700">{name}</span> '
                            f'<span style="color:#888;font-size:12px">\u2014 {provider_label}</span>',
                            unsafe_allow_html=True)
                st.markdown(opinion)
                st.markdown(_confidence_bar(confidence, "Confidence: "), unsafe_allow_html=True)
    ats = result.get("ats_bypass") or {}
    if ats:
        with st.expander("\U0001f916 ATS Bypass Tip", expanded=True):
            st.error(f"\u274c Don't say: `{ats.get('naive_answer', 'Yes')}`")
            st.success("\u2705 Say instead:")
            st.code(ats.get("smart_answer", ""), language=None)
            st.caption(ats.get("rationale", ""))
    outreach = result.get("linkedin_outreach") or ""
    if outreach:
        with st.expander("\U0001f517 LinkedIn Outreach Message"):
            st.text_area("Edit before sending:", value=outreach, height=140, key="outreach_msg")
    with st.expander("\U0001f52c Raw JSON"):
        st.json(result)


# ---------------------------------------------------------------------------
# Page: Applications
# ---------------------------------------------------------------------------

def tab_applications():
    st.subheader("\U0001f4cb Application Tracker")
    email = st.session_state.get("candidate_email", "")
    if not email:
        st.info("Enter your email in the sidebar to view applications.")
        return
    if not _backend_ready():
        st.warning("\u26a0\ufe0f Backend not running \u2014 start it from the sidebar.")
        return
    data, err = _get(f"/applications/{email}")
    if err or not data:
        st.error(
            f"Could not load applications.\n\n**Detail:** `{err or 'empty response'}`\n\n"
            "Restart the backend (\u25a0 Stop \u2192 \u25b6 Start in sidebar)."
        )
        return
    apps  = data.get("applications", [])
    total = data.get("total_applications", len(apps))
    if not apps:
        st.info("\U0001f4ed No applications yet. Run the AI Agent to start applying!")
        return
    counts = Counter((a.get("status") or "").lower() for a in apps)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total",     total)
    c2.metric("Draft",     counts.get("draft", 0))
    c3.metric("Submitted", counts.get("submitted", 0))
    c4.metric("Interview", counts.get("interview", 0))
    c5.metric("Rejected",  counts.get("rejected", 0))
    for app in apps:
        jd        = app.get("job") or {}
        job_title = jd.get("title") or app.get("job_title") or "Unknown role"
        company   = jd.get("company") or app.get("company") or "Unknown"
        job_url   = jd.get("url") or app.get("job_url") or ""
        with st.container(border=True):
            ca, cb, cc = st.columns([2, 2, 2])
            with ca:
                st.markdown(f"**{job_title}**")
                st.write(company)
                if job_url:
                    st.link_button("View", job_url)
            with cb:
                st.markdown(status_pill(app.get("status", "draft")), unsafe_allow_html=True)
                st.caption(f"Updated: {app.get('updated_at', EM_DASH)}")
            with cc:
                opts       = ["draft", "ready", "submitted", "interview", "rejected"]
                cur_status = app.get("status", "draft")
                cur        = cur_status if cur_status in opts else "draft"
                ns         = st.selectbox("Status", opts, index=opts.index(cur),
                                          key=f"s_{app['application_id']}")
                notes      = st.text_input("Notes", value=app.get("notes") or "",
                                           key=f"n_{app['application_id']}")
                if st.button("Save", key=f"sv_{app['application_id']}"):
                    res, e2 = _patch(
                        f"/applications/{app['application_id']}/status",
                        {"status": ns, "notes": notes or None, "run_id": None},
                    )
                    if res:
                        st.success("Saved")
                        st.rerun()
                    else:
                        st.error(e2)


# ---------------------------------------------------------------------------
# Page: Health
# ---------------------------------------------------------------------------

def tab_health():
    st.subheader("\U0001fa7a Diagnostics")
    status, detail = backend_status_info()
    icon = "\u2705" if status in ("Running", "Embedded") else "\u274c"
    st.write(f"{icon} **Backend:** {status} \u2014 {detail}")
    st.write(f"**Run mode:** `{'embedded (in-process)' if EMBEDDED else 'http'}`")
    st.write(f"**Python:** `{PYTHON_EXE}`")
    st.write(f"**Working dir:** `{BASE_DIR}`")
    if status not in ("Running", "Embedded") and LOG_FILE.exists():
        log_txt = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        if log_txt.strip():
            with st.expander("\U0001f4d4 Backend startup log", expanded=True):
                st.code(log_txt[-3000:], language="")
    st.markdown("### Package checks")
    pkg_list = [
        ("fastapi",    "fastapi",                     "Backend API"),
        ("uvicorn",    "uvicorn[standard]",            "Backend server"),
        ("pydantic",   "pydantic[email]",              "Data validation"),
        ("sqlalchemy", "sqlalchemy",                   "Database"),
        ("pypdf",      "pypdf",                        "PDF parsing"),
        ("docx",       "python-docx",                  "DOCX parsing"),
        ("jobspy",     "python-jobspy",                "Job scraping"),
        ("bs4",        "beautifulsoup4",               "HTML scraping"),
        ("requests",   "requests",                     "HTTP"),
        ("groq",       "groq",                         "Groq LLM (Phase 1)"),
        ("yaml",       "pyyaml",                       "Config"),
        ("openai",     "openai",                       "GPT (optional)"),
        ("anthropic",  "anthropic",                    "Claude (optional)"),
        ("reportlab",  "reportlab",                    "PDF export (optional)"),
        ("streamlit_autorefresh", "streamlit-autorefresh", "Auto-refresh (optional)"),
    ]
    for mod, pkg, desc in pkg_list:
        try:
            __import__(mod)
            st.success(f"\u2705 `{pkg}` \u2014 {desc}")
        except ImportError:
            marker = "\u26a0\ufe0f" if "optional" in desc else "\u274c"
            st.error(f"{marker} `{pkg}` NOT installed \u2014 `pip install {pkg}`")
    if status == "Running" and not EMBEDDED:
        data, _ = _get("/openapi.json")
        if data:
            st.write(f"**{len(data.get('paths', {}))} API routes active**")


# ---------------------------------------------------------------------------
# Main — state-machine entry point
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Job Application Copilot", page_icon="\U0001f916", layout="wide")
    # Copy Streamlit secrets into the environment before any backend import.
    _load_secrets_into_env()

    # ── Step 1: Initialise session defaults (runs only once per browser session) ──
    defaults = {
        "page":            PAGE_SETUP,
        "resume_profile":  None,
        "resume_filename": "",
        "candidate_email": "",
        "agent_launched":  False,
        "run_id":          None,
        "agent_status":    "idle",
        "agent_stage":     "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── Step 2: HARD PAGE-LOCK — before ANY widget is drawn ──────────────────────
    # If the agent is running, NOTHING can move us away from the agent page.
    # This guard runs every rerun, so autorefresh / button clicks cannot escape it.
    if st.session_state.get("agent_launched"):
        st.session_state["page"] = PAGE_AGENT

    # ── Step 3: Header & nav ─────────────────────────────────────────────────────
    st.title("\U0001f916 Job Application Copilot")
    st.caption("Upload CV \u2192 Agent scans every job board \u2192 instant cover letter + cold email per match")
    _render_nav()
    st.markdown("---")

    # ── Step 4: Sidebar ──────────────────────────────────────────────────────────
    be_status, be_detail = backend_status_info()
    with st.sidebar:
        st.header("\U0001f527 Controls")
        color = "green" if be_status in ("Running", "Embedded") else "red"
        st.markdown(f"**Backend:** :{color}[{be_status}]")
        st.caption(be_detail)
        # In embedded (single-process) mode there is no separate backend server
        # to start/stop, so those controls are hidden \u2014 the pipeline runs in-process.
        if not EMBEDDED:
            sc1, sc2 = st.columns(2)
            if sc1.button("\u25b6 Start", use_container_width=True, key="sb_start"):
                with st.spinner("Starting..."):
                    ok, msg = start_backend()
                st.success(msg) if ok else st.error(msg)
                st.rerun()
            if sc2.button("\u25a0 Stop", use_container_width=True, key="sb_stop"):
                ok, msg = stop_backend()
                st.success(msg) if ok else st.error(msg)
                st.rerun()
        st.markdown("---")
        st.session_state["candidate_email"] = st.text_input(
            "Your email",
            value=st.session_state["candidate_email"],
            placeholder="your@email.com",
            key="email_input",
        )
        p = st.session_state.get("resume_profile")
        if p:
            st.success(f"\U0001f4ce {st.session_state['resume_filename']}")
            name = _sidebar_name(p, st.session_state["resume_filename"])
            st.caption(
                f"{name} | {len(p.get('skills') or [])} skills "
                f"| {p.get('years_of_experience_hint') or '?'}"
            )
        else:
            st.info("\U0001f4ce Upload CV in \u2699\ufe0f Setup tab")
        if st.button("\u21bb Refresh", use_container_width=True, key="sb_refresh"):
            st.rerun()

    # ── Step 5: Render the active page ───────────────────────────────────────────
    page = st.session_state["page"]
    if page == PAGE_SETUP:
        tab_setup()
    elif page == PAGE_AGENT:
        tab_agent()
    elif page == PAGE_DEBATE:
        tab_debate()
    elif page == PAGE_APPS:
        tab_applications()
    elif page == PAGE_HEALTH:
        tab_health()


if __name__ == "__main__":
    main()
