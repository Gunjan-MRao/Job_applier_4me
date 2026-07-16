"""
Job Application Copilot — Streamlit frontend

Upgraded features:
- Resume-first onboarding (⚙️ Setup tab) — parses CV, extracts profile
- AI-powered job scoring shown live in the monitor
- Blacklist / whitelist company filter inputs
- Top-matches table rendered after run completes
- Cover letter preview per matched job
- Portable Python path (sys.executable — works on any machine)
- Session persistence across reruns via st.session_state
"""
import os
import signal
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import requests
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
API_HOST = "127.0.0.1"
API_PORT = 8000
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
PID_FILE = BASE_DIR / "runtime_api.pid"
CONDA_BASE_PYTHON = sys.executable   # always use the running Python
BACKEND_APP_IMPORT = "backend.main:app"
POLL_SECONDS = 3


# ---------------------------------------------------------------------------
# Backend process helpers
# ---------------------------------------------------------------------------

def is_port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_pid():
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pid(pid):
    PID_FILE.write_text(str(pid), encoding="utf-8")


def clear_pid():
    if PID_FILE.exists():
        PID_FILE.unlink()


def process_exists(pid):
    try:
        if os.name == "nt":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                    capture_output=True, text=True, timeout=5)
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def start_backend():
    if is_port_open(API_HOST, API_PORT):
        return True, "Backend is already running."
    cmd = [CONDA_BASE_PYTHON, "-m", "uvicorn", BACKEND_APP_IMPORT,
           "--host", API_HOST, "--port", str(API_PORT)]
    try:
        if os.name == "nt":
            proc = subprocess.Popen(cmd, cwd=str(BASE_DIR),
                                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(cmd, cwd=str(BASE_DIR), start_new_session=True)
        write_pid(proc.pid)
        for _ in range(20):
            if is_port_open(API_HOST, API_PORT):
                return True, f"Backend started on {API_BASE_URL}"
            time.sleep(0.5)
        return False, "Backend started but port not responding yet."
    except Exception as exc:
        return False, f"Failed to start backend: {exc}"


def stop_backend():
    pid = read_pid()
    if pid is None:
        return (True, "Backend already stopped.") if not is_port_open(API_HOST, API_PORT) \
            else (False, "Running but no PID file found.")
    if not process_exists(pid):
        clear_pid()
        return True, "Backend stopped (stale PID cleaned up)."
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           check=True, capture_output=True, timeout=10)
        else:
            os.kill(pid, signal.SIGTERM)
        clear_pid()
        for _ in range(10):
            if not is_port_open(API_HOST, API_PORT):
                return True, "Backend stopped."
            time.sleep(0.5)
        return True, "Stop signal sent."
    except Exception as exc:
        return False, f"Failed to stop: {exc}"


def get_backend_status():
    pid = read_pid()
    port_open = is_port_open(API_HOST, API_PORT)
    if port_open and pid and process_exists(pid):
        return "Running", f"Running on {API_BASE_URL} (PID {pid})"
    if port_open:
        return "Running", f"Running on {API_BASE_URL}"
    if pid and not process_exists(pid):
        clear_pid()
        return "Stopped", "Stopped (stale PID cleaned)."
    return "Stopped", "Backend is not running."


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def safe_get(url, timeout=10):
    try:
        return requests.get(url, timeout=timeout)
    except Exception as exc:
        return exc


def parse_resume_via_api(file_bytes, filename):
    try:
        resp = requests.post(f"{API_BASE_URL}/resume/parse",
                             files={"file": (filename, file_bytes, "application/octet-stream")},
                             timeout=30)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


def get_applications(candidate_email):
    try:
        resp = requests.get(f"{API_BASE_URL}/applications/{candidate_email}", timeout=10)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return {"candidate_email": candidate_email, "total_applications": 0, "applications": []}, str(exc)


def update_application_status(application_id, status, notes, run_id):
    payload = {"run_id": run_id or None, "status": status, "notes": notes or None}
    try:
        resp = requests.patch(f"{API_BASE_URL}/applications/{application_id}/status",
                              json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


def start_automation(payload: dict):
    try:
        resp = requests.post(f"{API_BASE_URL}/automation/start", json=payload, timeout=60)
        if resp.status_code == 404:
            return None, "POST /automation/start not found"
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


def get_automation_status(run_id: str):
    try:
        resp = requests.get(f"{API_BASE_URL}/automation/status/{run_id}", timeout=10)
        if resp.status_code == 404:
            return None, f"Run {run_id} not found"
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def status_badge(status: str) -> str:
    color_map = {"draft": "#f59e0b", "ready": "#3b82f6", "submitted": "#10b981",
                 "rejected": "#ef4444", "interview": "#8b5cf6", "running": "#0ea5e9",
                 "completed": "#10b981", "failed": "#ef4444", "queued": "#f59e0b"}
    color = color_map.get((status or "").lower(), "#6b7280")
    return (f'<div style="display:inline-block;padding:6px 14px;border-radius:999px;'
            f'background:{color}22;color:{color};font-weight:600;font-size:14px;'
            f'border:1px solid {color}55;">{status}</div>')


def render_tracker_summary(apps):
    counts = Counter((a.get("status") or "unknown").lower() for a in apps)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", len(apps))
    c2.metric("Draft", counts.get("draft", 0))
    c3.metric("Submitted", counts.get("submitted", 0))
    c4.metric("Interview", counts.get("interview", 0))
    c5.metric("Rejected", counts.get("rejected", 0))


# ---------------------------------------------------------------------------
# ⚙️ Setup tab
# ---------------------------------------------------------------------------

def render_setup_tab():
    st.subheader("Step 1 — Upload your resume")
    st.write(
        "Upload your CV (PDF or DOCX). The parser extracts your name, email, skills, and "
        "likely job roles. These auto-populate the search fields in the Live Monitor tab."
    )

    uploaded = st.file_uploader("Choose resume", type=["pdf", "docx"])
    if uploaded:
        file_bytes = uploaded.read()
        filename = uploaded.name
        st.info(f"Selected: **{filename}** ({len(file_bytes):,} bytes)")
        if st.button("Parse resume", type="primary"):
            with st.spinner("Parsing..."):
                profile, err = parse_resume_via_api(file_bytes, filename)
            if err:
                st.error(f"Parse failed: {err}")
            else:
                st.session_state.resume_profile = profile
                st.session_state.resume_filename = filename
                if profile.get("email") and not st.session_state.get("candidate_email"):
                    st.session_state.candidate_email = profile["email"]
                st.success("Resume parsed!")
                st.rerun()

    profile = st.session_state.get("resume_profile")
    if profile:
        st.markdown("### Extracted profile")
        p1, p2 = st.columns(2)
        with p1:
            st.write(f"**Name:** {profile.get('candidate_name') or '—'}")
            st.write(f"**Email:** {profile.get('email') or '—'}")
            st.write(f"**Phone:** {profile.get('phone') or '—'}")
            st.write(f"**Experience:** {profile.get('years_of_experience_hint') or '—'}")
        with p2:
            roles = profile.get("likely_roles") or []
            skills = profile.get("skills") or []
            st.write(f"**Likely roles ({len(roles)}):** {', '.join(roles) or '—'}")
            st.write(f"**Skills ({len(skills)}):** {', '.join(skills) or '—'}")
        st.text_area("Resume text preview", value=profile.get("preview", ""), height=180, disabled=True)
        st.info("Profile saved ✓ — switch to **🔴 Live Monitor** to start a run.")
    else:
        st.caption("No profile loaded yet.")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Job Application Copilot", page_icon="📄", layout="wide")

    for key, default in [
        ("active_run_id", ""), ("auto_refresh", False),
        ("resume_profile", None), ("resume_filename", ""),
        ("candidate_email", ""), ("last_refresh_ts", time.time()),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    st.title("Job Application Copilot")
    st.caption("Upload resume → scrape jobs → AI score → auto-apply. All in one place.")

    backend_status, backend_message = get_backend_status()

    # Sidebar
    with st.sidebar:
        st.header("Controls")
        st.write(f"**Backend:** {backend_status}")
        st.caption(backend_message)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶ Start", use_container_width=True):
                ok, msg = start_backend()
                (st.success if ok else st.error)(msg)
                st.rerun()
        with col2:
            if st.button("■ Stop", use_container_width=True):
                ok, msg = stop_backend()
                (st.success if ok else st.error)(msg)
                st.rerun()

        st.markdown("---")
        st.session_state.candidate_email = st.text_input(
            "Candidate email", value=st.session_state.candidate_email)
        st.session_state.auto_refresh = st.checkbox(
            "Auto-refresh monitor", value=st.session_state.auto_refresh)
        if st.button("↻ Refresh", use_container_width=True):
            st.rerun()
        if st.session_state.resume_filename:
            st.caption(f"📎 {st.session_state.resume_filename}")
        else:
            st.caption("No resume loaded — go to ⚙️ Setup")
        st.caption(f"Python: `{sys.executable}`")

    # Tabs
    tab_setup, tab_monitor, tab_matches, tab_applications, tab_health = st.tabs(
        ["⚙️ Setup", "🔴 Live Monitor", "🏆 Top Matches", "📋 Applications", "🩺 Health"])

    # --- Setup ---
    with tab_setup:
        if backend_status != "Running":
            st.warning("Start the backend first (sidebar), then upload your resume.")
        else:
            render_setup_tab()

    # --- Live Monitor ---
    with tab_monitor:
        if backend_status != "Running":
            st.warning("Backend not running. Start it from the sidebar.")
        else:
            st.subheader("Automation Monitor")
            if not st.session_state.resume_profile:
                st.info("💡 No resume loaded yet — go to **⚙️ Setup** first for best results.")

            profile = st.session_state.get("resume_profile") or {}
            default_kw = ", ".join(
                (profile.get("likely_roles") or []) + (profile.get("skills") or [])
            ) or "logistics, supply chain, operations"

            c1, c2, c3 = st.columns(3)
            with c1:
                target_keywords = st.text_input("Keywords (auto-filled from resume)", value=default_kw)
            with c2:
                target_location = st.text_input("Location", "United Kingdom")
            with c3:
                max_jobs = st.number_input("Max jobs", min_value=0, max_value=500, value=50, step=10,
                                           help="Set to 0 for deep unlimited crawl")

            with st.expander("Advanced filters"):
                bl_input = st.text_input("Company blacklist (comma-separated)", "")
                wl_input = st.text_input("Company whitelist (comma-separated, optional)", "")
                auto_apply = st.checkbox("Auto-apply (generate cover letters)", value=True)

            c4, c5 = st.columns([1, 2])
            with c4:
                if st.button("🚀 Start run", type="primary", use_container_width=True):
                    payload = {
                        "candidate_email": st.session_state.candidate_email or "user@example.com",
                        "keywords": [x.strip() for x in target_keywords.split(",") if x.strip()],
                        "location": target_location,
                        "max_jobs": int(max_jobs),
                        "auto_apply": auto_apply,
                        "track_live": True,
                        "resume_filename": st.session_state.resume_filename or None,
                        "resume_profile": st.session_state.resume_profile,
                        "company_blacklist": [x.strip() for x in bl_input.split(",") if x.strip()],
                        "company_whitelist": [x.strip() for x in wl_input.split(",") if x.strip()],
                    }
                    result, err = start_automation(payload)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.active_run_id = result.get("run_id", "")
                        st.success(f"Run started: `{st.session_state.active_run_id}`")
                        st.rerun()

            with c5:
                active_run_id = st.text_input("Active run ID", value=st.session_state.active_run_id)
                st.session_state.active_run_id = active_run_id

            if st.session_state.active_run_id:
                status_data, status_err = get_automation_status(st.session_state.active_run_id)
                if status_err:
                    st.info(status_err)
                else:
                    state = status_data.get("status", "unknown")
                    stage = status_data.get("stage", "unknown")
                    progress = status_data.get("progress_percent", 0)

                    st.markdown(status_badge(state), unsafe_allow_html=True)
                    st.write(f"**Stage:** {stage}")
                    st.progress(min(max(int(progress), 0), 100))

                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Scanned", status_data.get("jobs_scanned", 0))
                    k2.metric("Matched", status_data.get("jobs_matched", 0))
                    k3.metric("Applied", status_data.get("jobs_applied", 0))
                    k4.metric("Failed", status_data.get("jobs_failed", 0))

                    if status_data.get("current_url"):
                        st.write(f"**Current:** {status_data['current_url']}")

                    logs = status_data.get("logs", [])
                    with st.expander("Live log", expanded=state in {"running", "queued"}):
                        for entry in logs[-30:]:
                            lvl = entry.get("level", "info")
                            icon = "✅" if lvl == "info" else ("⚠️" if lvl == "warning" else "❌")
                            st.code(f"{entry.get('ts','')} {icon} {entry.get('message','')}")

                    if st.session_state.auto_refresh and state.lower() in {"queued", "running"}:
                        time.sleep(POLL_SECONDS)
                        st.rerun()
            else:
                st.info("No active run selected.")

    # --- Top Matches ---
    with tab_matches:
        if backend_status != "Running":
            st.warning("Backend not running.")
        elif not st.session_state.active_run_id:
            st.info("Start a run in Live Monitor first.")
        else:
            st.subheader("Top Matched Jobs")
            status_data, err = get_automation_status(st.session_state.active_run_id)
            if err:
                st.error(err)
            else:
                top = (status_data.get("top_matches") or
                       (status_data.get("result_summary") or {}).get("top_matches") or [])
                if not top:
                    st.info("No matches yet — run may still be in progress.")
                else:
                    st.write(f"Showing top {len(top)} matches by AI fit score:")
                    for i, m in enumerate(top, 1):
                        with st.container(border=True):
                            col_a, col_b, col_c = st.columns([3, 2, 1])
                            col_a.markdown(f"**{i}. {m.get('title', '?')}** at {m.get('company', '?')}")
                            col_b.progress(min(m.get("fit_score", 0), 100),
                                           text=f"Fit: {m.get('fit_score', 0)}%")
                            if m.get("url"):
                                col_c.link_button("Open", m["url"])

    # --- Applications ---
    with tab_applications:
        if backend_status != "Running":
            st.warning("Backend not running.")
        else:
            st.subheader("Application Tracker")
            data, error = get_applications(st.session_state.candidate_email)
            if error:
                st.error(f"Error: {error}")
            else:
                apps = data.get("applications", [])
                st.write(f"**Candidate:** {st.session_state.candidate_email} | **Total:** {data.get('total_applications', 0)}")
                render_tracker_summary(apps)
                if not apps:
                    st.info("No applications yet.")
                else:
                    for app in apps:
                        with st.container(border=True):
                            col1, col2, col3 = st.columns([2, 2, 2])
                            with col1:
                                st.markdown(f"### {app['job']['title']}")
                                st.write(f"**Company:** {app['job']['company']}")
                                if app["job"].get("url"):
                                    st.link_button("Open", app["job"]["url"])
                            with col2:
                                st.markdown(status_badge(app["status"]), unsafe_allow_html=True)
                                st.write(f"**Resume:** {app['resume_filename']}")
                                st.write(f"**Updated:** {app['updated_at']}")
                            with col3:
                                options = ["draft", "ready", "submitted", "interview", "rejected"]
                                new_status = st.selectbox("Status", options,
                                    index=options.index(app["status"]) if app["status"] in options else 0,
                                    key=f"st_{app['application_id']}")
                                notes = st.text_input("Notes", value=app.get("notes") or "",
                                                      key=f"n_{app['application_id']}")
                                if st.button("Save", key=f"sv_{app['application_id']}"):
                                    res, err2 = update_application_status(
                                        app["application_id"], new_status, notes, st.session_state.active_run_id)
                                    (st.success if res else st.error)(f"Updated to {new_status}" if res else err2)
                                    if res:
                                        st.rerun()

    # --- Health ---
    with tab_health:
        if backend_status != "Running":
            st.warning("Backend not running.")
        else:
            st.subheader("Backend Health")
            docs = safe_get(f"{API_BASE_URL}/docs", timeout=5)
            (st.success if not isinstance(docs, Exception) else st.error)(
                "FastAPI /docs reachable" if not isinstance(docs, Exception) else str(docs))

            openapi = safe_get(f"{API_BASE_URL}/openapi.json", timeout=5)
            if not isinstance(openapi, Exception):
                try:
                    schema = openapi.json()
                    paths = sorted(schema.get("paths", {}).keys())
                    st.write(f"**API paths ({len(paths)}):** {', '.join(paths)}")
                except Exception:
                    pass

            try:
                from jobspy import scrape_jobs as _test  # noqa
                st.success("✅ jobspy is importable (direct in-process scraping active)")
            except ImportError:
                st.warning("⚠️ jobspy not installed — using HTTP sidecar fallback. Run: pip install python-jobspy")

            st.write(f"**Python:** `{sys.executable}`")


if __name__ == "__main__":
    main()
