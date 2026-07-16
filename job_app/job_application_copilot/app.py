"""
Job Application Copilot — Streamlit frontend v3

Fixes in this version:
- Backend start now works even when Python path contains spaces (quoted args)
- Resume upload works WITHOUT the backend (parses locally in-process)
- AI Agent tab: end-to-end autonomous loop with live status + auto-retry
- Health tab shows exactly WHY the backend failed to start
- Backend logs shown in sidebar so you can see startup errors
"""
import json
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
from typing import Optional

import requests
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
API_HOST = "127.0.0.1"
API_PORT = 8000
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
PID_FILE = BASE_DIR / "runtime_api.pid"
LOG_FILE = BASE_DIR / "backend_startup.log"
PYTHON_EXE = sys.executable          # always the running Python
POLL_SECONDS = 4


# ---------------------------------------------------------------------------
# Backend helpers
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
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                               capture_output=True, text=True, timeout=5)
            return str(pid) in r.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def start_backend():
    if is_port_open():
        return True, "Backend already running."

    # Quote the python executable in case path contains spaces
    cmd = [
        PYTHON_EXE, "-m", "uvicorn",
        "backend.main:app",
        "--host", API_HOST,
        "--port", str(API_PORT),
        "--log-level", "info",
    ]
    LOG_FILE.write_text("", encoding="utf-8")  # clear log
    try:
        if os.name == "nt":
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=open(LOG_FILE, "w"),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=open(LOG_FILE, "w"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        # Wait up to 15 s
        for _ in range(30):
            if is_port_open():
                return True, f"Backend started (PID {proc.pid})"
            time.sleep(0.5)
        # Still not up — show log
        log_tail = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-1200:] if LOG_FILE.exists() else ""
        return False, f"Backend did not respond in 15s.\n\nStartup log:\n{log_tail}"
    except Exception as exc:
        return False, f"Could not launch backend process: {exc}"


def stop_backend():
    pid = read_pid()
    if not is_port_open() and not process_alive(pid):
        if PID_FILE.exists():
            PID_FILE.unlink()
        return True, "Backend already stopped."
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
    pid = read_pid()
    if is_port_open():
        label = "Running"
        detail = f"Listening on {API_BASE_URL}"
        if pid and process_alive(pid):
            detail += f" (PID {pid})"
        return label, detail
    if pid and process_alive(pid):
        return "Starting", f"Process {pid} alive but port not open yet"
    if PID_FILE.exists():
        PID_FILE.unlink()
    return "Stopped", "Not running"


# ---------------------------------------------------------------------------
# Local resume parser (works WITHOUT backend)
# ---------------------------------------------------------------------------

def _parse_resume_local(file_bytes: bytes, filename: str) -> dict:
    """Runs the same parser logic as the backend, but in-process — no HTTP call needed."""
    import tempfile
    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)
    try:
        from backend.services.parser.resume_parser import build_profile_preview
        profile = build_profile_preview(filename, _extract_text(tmp_path))
    except Exception:
        # Pure fallback if backend package not importable
        text = _extract_text_raw(file_bytes, suffix)
        profile = _minimal_parse(filename, text)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
    return profile


def _extract_text(path: Path) -> str:
    try:
        from backend.services.parser.resume_parser import extract_resume_text
        return extract_resume_text(path)
    except Exception:
        return _extract_text_raw(path.read_bytes(), path.suffix.lower())


def _extract_text_raw(file_bytes: bytes, suffix: str) -> str:
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(file_bytes))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        if suffix == ".docx":
            from docx import Document
            doc = Document(BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        pass
    return ""


def _minimal_parse(filename: str, text: str) -> dict:
    import re as _re
    email_m = _re.search(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", text, _re.I)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    name = lines[0][:60] if lines else None
    skills_kw = ["python", "sql", "excel", "supply chain", "logistics", "procurement",
                 "sap", "operations", "forecasting", "power bi", "tableau", "aws", "azure"]
    skills = [s for s in skills_kw if s in text.lower()]
    return {
        "filename": filename,
        "candidate_name": name,
        "email": email_m.group(0) if email_m else None,
        "phone": None,
        "skills": skills,
        "likely_roles": [],
        "years_of_experience_hint": None,
        "preview": " ".join(text.split())[:600],
    }


def parse_resume_via_api(file_bytes: bytes, filename: str):
    """Try backend API first; fall back to local parse if backend not up."""
    if is_port_open():
        try:
            resp = requests.post(
                f"{API_BASE_URL}/resume/parse",
                files={"file": (filename, file_bytes, "application/octet-stream")},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json(), None
        except Exception as exc:
            pass  # fall through to local
    # Local fallback
    try:
        profile = _parse_resume_local(file_bytes, filename)
        return profile, None
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _api_get(path, timeout=10):
    try:
        r = requests.get(f"{API_BASE_URL}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _api_post(path, payload, timeout=60):
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _api_patch(path, payload, timeout=10):
    try:
        r = requests.patch(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def start_automation(payload: dict):
    return _api_post("/automation/start", payload)


def get_automation_status(run_id: str):
    return _api_get(f"/automation/status/{run_id}")


def get_applications(email: str):
    data, err = _api_get(f"/applications/{email}")
    if err:
        return {"candidate_email": email, "total_applications": 0, "applications": []}, err
    return data, None


def update_application_status(app_id, status, notes, run_id):
    return _api_patch(f"/applications/{app_id}/status",
                      {"run_id": run_id or None, "status": status, "notes": notes or None})


# ---------------------------------------------------------------------------
# AI Agent loop (runs in background thread, writes to session state log)
# ---------------------------------------------------------------------------

AGENT_STATE: dict = {}          # shared across reruns via module-level dict
AGENT_LOCK = threading.Lock()


def _agent_log(msg: str):
    with AGENT_LOCK:
        AGENT_STATE.setdefault("log", []).append(
            f"[{time.strftime('%H:%M:%S')}] {msg}")
        AGENT_STATE["log"] = AGENT_STATE["log"][-200:]


def _agent_thread(config: dict):
    """Background AI agent: starts backend if needed, launches run, monitors until done."""
    with AGENT_LOCK:
        AGENT_STATE["running"] = True
        AGENT_STATE["status"] = "starting"
        AGENT_STATE["run_id"] = None
        AGENT_STATE["summary"] = None
        AGENT_STATE["top_matches"] = []

    _agent_log("Agent started.")

    # Step 1: ensure backend is up
    if not is_port_open():
        _agent_log("Backend not running — starting it...")
        ok, msg = start_backend()
        if ok:
            _agent_log(f"Backend started. {msg}")
        else:
            _agent_log(f"FAILED to start backend: {msg}")
            with AGENT_LOCK:
                AGENT_STATE["running"] = False
                AGENT_STATE["status"] = "failed"
            return
    else:
        _agent_log("Backend already running.")

    # Step 2: launch automation run
    _agent_log(f"Launching automation run: keywords={config.get('keywords')}, location={config.get('location')}")
    with AGENT_LOCK:
        AGENT_STATE["status"] = "running"

    result, err = start_automation(config)
    if err or not result:
        _agent_log(f"Failed to start automation: {err}")
        with AGENT_LOCK:
            AGENT_STATE["running"] = False
            AGENT_STATE["status"] = "failed"
        return

    run_id = result.get("run_id", "")
    with AGENT_LOCK:
        AGENT_STATE["run_id"] = run_id
    _agent_log(f"Run started: {run_id}")

    # Step 3: poll until done (with auto-retry on transient errors)
    retries = 0
    max_retries = 5
    while True:
        time.sleep(POLL_SECONDS)
        status_data, poll_err = get_automation_status(run_id)
        if poll_err:
            retries += 1
            _agent_log(f"Poll error ({retries}/{max_retries}): {poll_err}")
            if retries >= max_retries:
                _agent_log("Max retries reached. Agent stopping.")
                with AGENT_LOCK:
                    AGENT_STATE["running"] = False
                    AGENT_STATE["status"] = "failed"
                return
            continue
        retries = 0

        state = status_data.get("status", "unknown")
        stage = status_data.get("stage", "")
        progress = status_data.get("progress_percent", 0)
        scanned = status_data.get("jobs_scanned", 0)
        matched = status_data.get("jobs_matched", 0)
        applied = status_data.get("jobs_applied", 0)

        with AGENT_LOCK:
            AGENT_STATE["status"] = state
            AGENT_STATE["progress"] = progress
            AGENT_STATE["stage"] = stage
            AGENT_STATE["scanned"] = scanned
            AGENT_STATE["matched"] = matched
            AGENT_STATE["applied"] = applied
            AGENT_STATE["top_matches"] = (
                status_data.get("top_matches")
                or (status_data.get("result_summary") or {}).get("top_matches")
                or []
            )

        _agent_log(f"Stage={stage} progress={progress}% scanned={scanned} matched={matched} applied={applied}")

        if state in ("completed", "failed"):
            summary = status_data.get("result_summary") or {}
            with AGENT_LOCK:
                AGENT_STATE["summary"] = summary
                AGENT_STATE["running"] = False
            if state == "completed":
                _agent_log(f"✅ DONE. {scanned} scanned, {matched} matched, {applied} applied.")
                if AGENT_STATE["top_matches"]:
                    _agent_log("Top matches:")
                    for m in AGENT_STATE["top_matches"][:5]:
                        _agent_log(f"  ★ {m.get('title')} at {m.get('company')} — fit {m.get('fit_score')}%")
            else:
                _agent_log("❌ Run failed.")
            return


def launch_agent(config: dict):
    t = threading.Thread(target=_agent_thread, args=(config,), daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def badge(status: str) -> str:
    c = {"running": "#0ea5e9", "completed": "#10b981", "failed": "#ef4444",
         "queued": "#f59e0b", "starting": "#f59e0b", "stopped": "#6b7280",
         "draft": "#f59e0b", "submitted": "#10b981",
         "rejected": "#ef4444", "interview": "#8b5cf6"}.get((status or "").lower(), "#6b7280")
    return (f'<span style="padding:4px 12px;border-radius:999px;background:{c}22;'
            f'color:{c};font-weight:700;font-size:13px;border:1px solid {c}66;">{status}</span>')


def tracker_summary(apps):
    counts = Counter((a.get("status") or "").lower() for a in apps)
    cols = st.columns(5)
    for col, (label, key) in zip(cols, [
        ("Total", None), ("Draft", "draft"), ("Submitted", "submitted"),
        ("Interview", "interview"), ("Rejected", "rejected")
    ]):
        col.metric(label, len(apps) if key is None else counts.get(key, 0))


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def tab_setup():
    st.subheader("⚙️ Setup — Upload your resume")
    st.write(
        "Your resume is parsed **locally** — you don't need to start the backend first. "
        "Extracted skills and roles will auto-fill the AI Agent search fields."
    )

    uploaded = st.file_uploader("Choose your CV (PDF or DOCX)", type=["pdf", "docx"],
                                 key="cv_uploader")
    if uploaded:
        file_bytes = uploaded.read()
        st.info(f"Selected: **{uploaded.name}** ({len(file_bytes):,} bytes)")
        if st.button("Parse resume ➤", type="primary"):
            with st.spinner("Parsing your CV..."):
                profile, err = parse_resume_via_api(file_bytes, uploaded.name)
            if err:
                st.error(f"Parse error: {err}")
            else:
                st.session_state.resume_profile = profile
                st.session_state.resume_filename = uploaded.name
                if profile.get("email") and not st.session_state.get("candidate_email"):
                    st.session_state.candidate_email = profile["email"]
                st.success("✅ Resume parsed! Switch to **🤖 AI Agent** to start your job search.")
                st.rerun()

    profile = st.session_state.get("resume_profile")
    if profile:
        st.markdown("### 📌 Extracted profile")
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"👤 **Name:** {profile.get('candidate_name') or '—'}")
            st.write(f"📧 **Email:** {profile.get('email') or '—'}")
            st.write(f"📞 **Phone:** {profile.get('phone') or '—'}")
            st.write(f"💼 **Experience:** {profile.get('years_of_experience_hint') or '—'}")
        with c2:
            roles = profile.get("likely_roles") or []
            skills = profile.get("skills") or []
            st.write(f"🎯 **Target roles ({len(roles)}):** {', '.join(roles) or '—'}")
            st.write(f"⚙️ **Skills ({len(skills)}):** {', '.join(skills) or '—'}")
        if profile.get("preview"):
            with st.expander("Resume text preview"):
                st.text(profile["preview"])
    else:
        st.caption("ℹ️ Upload a CV above to get started.")


def tab_agent():
    st.subheader("🤖 AI Agent — End-to-End Job Search")
    st.write(
        "The agent **handles everything**: starts the backend if needed, scrapes jobs from "
        "LinkedIn / Indeed / Glassdoor / Reed / NHS / GOV.UK and more, scores each job "
        "against your resume, filters out no-sponsorship roles, generates cover letters, "
        "and reports back — all without you doing anything after clicking Start."
    )

    profile = st.session_state.get("resume_profile") or {}
    if not profile:
        st.warning("⚠️ No resume loaded. Go to **⚙️ Setup** first for best results.")

    default_kw = ", ".join(
        (profile.get("likely_roles") or []) + (profile.get("skills") or [])
    ) or "logistics, supply chain, operations"

    with st.form("agent_form"):
        c1, c2, c3 = st.columns(3)
        keywords = c1.text_input("Keywords", value=default_kw)
        location = c2.text_input("Location", "United Kingdom")
        max_jobs = c3.number_input("Max jobs to scan", min_value=10, max_value=500, value=50, step=10)

        with st.expander("🔧 Advanced filters"):
            blacklist = st.text_input("Blacklist companies (comma-separated)", "")
            whitelist = st.text_input("Whitelist companies (only apply here, optional)", "")
            auto_apply = st.checkbox("Auto-generate cover letters", value=True)

        start_clicked = st.form_submit_button("🚀 Start AI Agent", type="primary", use_container_width=True)

    if start_clicked:
        with AGENT_LOCK:
            already_running = AGENT_STATE.get("running", False)
        if already_running:
            st.warning("Agent is already running. Scroll down to see live status.")
        else:
            config = {
                "candidate_email": st.session_state.get("candidate_email") or "user@example.com",
                "keywords": [x.strip() for x in keywords.split(",") if x.strip()],
                "location": location,
                "max_jobs": int(max_jobs),
                "auto_apply": auto_apply,
                "track_live": True,
                "resume_filename": st.session_state.get("resume_filename") or None,
                "resume_profile": profile or None,
                "company_blacklist": [x.strip() for x in blacklist.split(",") if x.strip()],
                "company_whitelist": [x.strip() for x in whitelist.split(",") if x.strip()],
            }
            with AGENT_LOCK:
                AGENT_STATE.clear()
                AGENT_STATE["log"] = []
            launch_agent(config)
            st.success("🤖 Agent launched! Live status below (page auto-refreshes).")
            time.sleep(1)
            st.rerun()

    # Live status panel
    with AGENT_LOCK:
        agent_running = AGENT_STATE.get("running", False)
        agent_status = AGENT_STATE.get("status", "idle")
        agent_progress = AGENT_STATE.get("progress", 0)
        agent_stage = AGENT_STATE.get("stage", "")
        agent_log = list(AGENT_STATE.get("log", []))
        agent_matches = list(AGENT_STATE.get("top_matches", []))
        agent_summary = AGENT_STATE.get("summary")
        scanned = AGENT_STATE.get("scanned", 0)
        matched = AGENT_STATE.get("matched", 0)
        applied = AGENT_STATE.get("applied", 0)

    if agent_status != "idle":
        st.markdown("---")
        st.markdown(f"**Agent status:** {badge(agent_status)}", unsafe_allow_html=True)
        if agent_stage:
            st.write(f"**Stage:** `{agent_stage}`")
        st.progress(min(max(int(agent_progress), 0), 100))

        m1, m2, m3 = st.columns(3)
        m1.metric("🔍 Scanned", scanned)
        m2.metric("✅ Matched", matched)
        m3.metric("📤 Applied", applied)

        with st.expander("📝 Agent log", expanded=agent_running):
            for line in reversed(agent_log[-40:]):
                st.code(line, language=None)

        if agent_matches:
            st.markdown("### 🏆 Top matches so far")
            for i, m in enumerate(agent_matches[:10], 1):
                c_a, c_b, c_c = st.columns([3, 2, 1])
                c_a.markdown(f"**{i}. {m.get('title', '?')}** — {m.get('company', '?')}")
                score = m.get("fit_score", 0)
                c_b.progress(min(score, 100), text=f"Fit: {score}%")
                if m.get("url"):
                    c_c.link_button("🔗 Open", m["url"])

        if agent_summary:
            with st.expander("📈 Final summary"):
                st.json(agent_summary)

        if agent_running:
            time.sleep(POLL_SECONDS)
            st.rerun()
        elif agent_status == "completed":
            if st.button("🔄 Run again"):
                with AGENT_LOCK:
                    AGENT_STATE.clear()
                st.rerun()


def tab_applications():
    st.subheader("📋 Application Tracker")
    email = st.session_state.get("candidate_email", "")
    if not email:
        st.info("Enter your email in the sidebar.")
        return
    if not is_port_open():
        st.warning("Backend not running — start it from the sidebar to see applications.")
        return
    data, err = get_applications(email)
    if err:
        st.error(err)
        return
    apps = data.get("applications", [])
    st.write(f"**{email}** — {data.get('total_applications', 0)} applications")
    tracker_summary(apps)
    if not apps:
        st.info("No applications recorded yet.")
        return
    for app in apps:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 2, 2])
            with c1:
                st.markdown(f"**{app['job']['title']}**")
                st.write(f"{app['job']['company']}")
                if app["job"].get("url"):
                    st.link_button("View job", app["job"]["url"])
            with c2:
                st.markdown(badge(app["status"]), unsafe_allow_html=True)
                st.caption(f"Updated: {app['updated_at']}")
            with c3:
                opts = ["draft", "ready", "submitted", "interview", "rejected"]
                new_st = st.selectbox("Status", opts,
                    index=opts.index(app["status"]) if app["status"] in opts else 0,
                    key=f"s_{app['application_id']}")
                notes = st.text_input("Notes", value=app.get("notes") or "",
                                      key=f"n_{app['application_id']}")
                if st.button("Save", key=f"sv_{app['application_id']}"):
                    res, e2 = update_application_status(
                        app["application_id"], new_st, notes,
                        st.session_state.get("active_run_id"))
                    (st.success if res else st.error)(
                        f"Saved as {new_st}" if res else e2)
                    if res:
                        st.rerun()


def tab_health():
    st.subheader("🩺 Diagnostics")

    status, detail = backend_status_info()
    icon = "✅" if status == "Running" else "❌"
    st.write(f"{icon} **Backend:** {status} — {detail}")
    st.write(f"**Python:** `{PYTHON_EXE}`")
    st.write(f"**Working directory:** `{BASE_DIR}`")

    # Show startup log if backend not running
    if status != "Running" and LOG_FILE.exists():
        log_text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        if log_text.strip():
            with st.expander("📔 Backend startup log (last attempt)", expanded=True):
                st.code(log_text[-3000:], language="") 

    # Package checks
    st.markdown("### Package status")
    packages = [
        ("jobspy", "python-jobspy", "Direct in-process scraping"),
        ("openai", "openai", "GPT-4o-mini cover letters"),
        ("anthropic", "anthropic", "Claude cover letters"),
        ("pypdf", "pypdf", "PDF resume parsing"),
        ("docx", "python-docx", "DOCX resume parsing"),
        ("fastapi", "fastapi", "Backend API"),
        ("uvicorn", "uvicorn", "Backend server"),
        ("bs4", "beautifulsoup4", "HTML scraping"),
    ]
    for mod, pkg, desc in packages:
        try:
            __import__(mod)
            st.success(f"✅ `{pkg}` — {desc}")
        except ImportError:
            st.error(f"❌ `{pkg}` not installed — {desc}. Run: `pip install {pkg}`")

    # API routes (if running)
    if status == "Running":
        data, err = _api_get("/openapi.json")
        if data:
            paths = sorted(data.get("paths", {}).keys())
            st.write(f"**{len(paths)} API routes:** {', '.join(paths)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Job Application Copilot",
                       page_icon="🤖", layout="wide")

    # Init session state
    defaults = {
        "resume_profile": None,
        "resume_filename": "",
        "candidate_email": "",
        "active_run_id": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    st.title("🤖 Job Application Copilot")
    st.caption("Upload resume → AI Agent scrapes + scores + applies — fully automated.")

    status, detail = backend_status_info()

    # --- Sidebar ---
    with st.sidebar:
        st.header("🔧 Controls")
        color = "green" if status == "Running" else "red"
        st.markdown(f"**Backend:** :{color}[{status}]")
        st.caption(detail)

        c1, c2 = st.columns(2)
        if c1.button("▶ Start", use_container_width=True):
            with st.spinner("Starting backend..."):
                ok, msg = start_backend()
            (st.success if ok else st.error)(msg)
            st.rerun()
        if c2.button("■ Stop", use_container_width=True):
            ok, msg = stop_backend()
            (st.success if ok else st.error)(msg)
            st.rerun()

        st.markdown("---")
        st.session_state.candidate_email = st.text_input(
            "Your email", value=st.session_state.candidate_email,
            placeholder="your@email.com")

        profile = st.session_state.get("resume_profile")
        if profile:
            st.success(f"📎 {st.session_state.resume_filename}")
            st.caption(f"Name: {profile.get('candidate_name') or '?'}")
            st.caption(f"Skills: {len(profile.get('skills') or [])} found")
        else:
            st.info("📎 No resume — go to ⚙️ Setup")

        if st.button("↻ Refresh page", use_container_width=True):
            st.rerun()

    # --- Tabs ---
    t1, t2, t3, t4 = st.tabs(["⚙️ Setup", "🤖 AI Agent", "📋 Applications", "🩺 Health"])

    with t1:
        tab_setup()
    with t2:
        tab_agent()
    with t3:
        tab_applications()
    with t4:
        tab_health()


if __name__ == "__main__":
    main()
