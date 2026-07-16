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

# Always use the same Python that is running Streamlit — works on any machine
CONDA_BASE_PYTHON = sys.executable
BACKEND_APP_IMPORT = "backend.main:app"

DEFAULT_EMAIL = ""
DEFAULT_RUN_ID = ""

POLL_SECONDS = 3


# ---------------------------------------------------------------------------
# Backend process helpers
# ---------------------------------------------------------------------------

def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid), encoding="utf-8")


def clear_pid() -> None:
    if PID_FILE.exists():
        PID_FILE.unlink()


def process_exists(pid: int) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def start_backend() -> tuple[bool, str]:
    if is_port_open(API_HOST, API_PORT):
        return True, "Backend is already running."

    cmd = [
        CONDA_BASE_PYTHON,
        "-m",
        "uvicorn",
        BACKEND_APP_IMPORT,
        "--host",
        API_HOST,
        "--port",
        str(API_PORT),
    ]

    try:
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NEW_CONSOLE
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                creationflags=creation_flags,
            )
        else:
            proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                start_new_session=True,
            )

        write_pid(proc.pid)

        for _ in range(20):
            if is_port_open(API_HOST, API_PORT):
                return True, f"Backend started successfully on {API_BASE_URL}"
            time.sleep(0.5)

        return False, "Backend process started, but API port did not open in time. Check backend console."
    except Exception as exc:
        return False, f"Failed to start backend: {exc}"


def stop_backend() -> tuple[bool, str]:
    pid = read_pid()

    if pid is None:
        if is_port_open(API_HOST, API_PORT):
            return False, "Backend is running, but no PID file was found."
        return True, "Backend is already stopped."

    if not process_exists(pid):
        clear_pid()
        return True, "Backend is stopped. Old PID file was cleaned up."

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            os.kill(pid, signal.SIGTERM)

        clear_pid()

        for _ in range(10):
            if not is_port_open(API_HOST, API_PORT):
                return True, "Backend stopped successfully."
            time.sleep(0.5)

        return True, "Stop command sent. Backend may still be shutting down."
    except Exception as exc:
        return False, f"Failed to stop backend: {exc}"


def get_backend_status() -> tuple[str, str]:
    pid = read_pid()
    port_open = is_port_open(API_HOST, API_PORT)

    if port_open and pid and process_exists(pid):
        return "Running", f"Backend is running on {API_BASE_URL} (PID {pid})"
    if port_open:
        return "Running", f"Backend is running on {API_BASE_URL}"
    if pid and not process_exists(pid):
        clear_pid()
        return "Stopped", "Backend is stopped. Old PID file was cleaned up."
    return "Stopped", "Backend is not running."


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def safe_get(url: str, timeout: int = 10):
    try:
        r = requests.get(url, timeout=timeout)
        return r
    except Exception as exc:
        return exc


def parse_resume_via_api(file_bytes: bytes, filename: str) -> tuple[dict | None, str | None]:
    """POST to /resume/parse and return the profile dict or an error string."""
    try:
        resp = requests.post(
            f"{API_BASE_URL}/resume/parse",
            files={"file": (filename, file_bytes, "application/octet-stream")},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


def get_applications(candidate_email: str):
    try:
        resp = requests.get(f"{API_BASE_URL}/applications/{candidate_email}", timeout=10)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return {
            "candidate_email": candidate_email,
            "total_applications": 0,
            "applications": [],
        }, str(exc)


def update_application_status(application_id: str, status: str, notes: str | None, run_id: str | None):
    payload = {
        "run_id": run_id or None,
        "status": status,
        "notes": notes or None,
    }
    try:
        resp = requests.patch(
            f"{API_BASE_URL}/applications/{application_id}/status",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


def start_automation(payload: dict):
    try:
        resp = requests.post(f"{API_BASE_URL}/automation/start", json=payload, timeout=60)
        if resp.status_code == 404:
            return None, "Automation start endpoint not found yet: POST /automation/start"
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


def get_automation_status(run_id: str):
    try:
        resp = requests.get(f"{API_BASE_URL}/automation/status/{run_id}", timeout=10)
        if resp.status_code == 404:
            return None, "Automation status endpoint not found yet: GET /automation/status/{run_id}"
        resp.raise_for_status()
        return resp.json(), None
    except Exception as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def status_badge(status: str) -> str:
    color_map = {
        "draft": "#f59e0b",
        "ready": "#3b82f6",
        "submitted": "#10b981",
        "rejected": "#ef4444",
        "interview": "#8b5cf6",
        "running": "#0ea5e9",
        "completed": "#10b981",
        "failed": "#ef4444",
        "queued": "#f59e0b",
    }
    color = color_map.get((status or "").lower(), "#6b7280")
    return f"""
    <div style="
        display:inline-block;
        padding:6px 12px;
        border-radius:999px;
        background:{color}22;
        color:{color};
        font-weight:600;
        font-size:14px;
        border:1px solid {color}55;
    ">
        {status}
    </div>
    """


def render_tracker_summary(apps: list[dict]):
    counts = Counter((app.get("status") or "unknown").lower() for app in apps)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", len(apps))
    c2.metric("Draft", counts.get("draft", 0))
    c3.metric("Submitted", counts.get("submitted", 0))
    c4.metric("Interview", counts.get("interview", 0))
    c5.metric("Rejected", counts.get("rejected", 0))


def render_application_card(app: dict, run_id: str):
    with st.container(border=True):
        col1, col2, col3 = st.columns([2, 2, 2])

        with col1:
            st.markdown(f"### {app['job']['title']}")
            st.write(f"**Company:** {app['job']['company']}")
            if app["job"].get("location"):
                st.write(f"**Location:** {app['job']['location']}")
            if app["job"].get("source"):
                st.write(f"**Source:** {app['job']['source']}")
            if app["job"].get("url"):
                st.link_button("Open job link", app["job"]["url"])

        with col2:
            st.markdown(status_badge(app["status"]), unsafe_allow_html=True)
            st.write(f"**Resume:** {app['resume_filename']}")
            st.write(f"**Format:** {app['resume_format']}")
            st.write(f"**Version ID:** `{app['resume_version_id']}`")
            st.write(f"**Created:** {app['created_at']}")
            st.write(f"**Updated:** {app['updated_at']}")
            if app.get("notes"):
                st.write(f"**Notes:** {app['notes']}")

        with col3:
            options = ["draft", "ready", "submitted", "interview", "rejected"]
            current_status = app["status"] if app["status"] in options else "draft"

            new_status = st.selectbox(
                "Change status",
                options,
                index=options.index(current_status),
                key=f"status_{app['application_id']}",
            )

            notes_input = st.text_input(
                "Update notes",
                value=app.get("notes") or "",
                key=f"notes_{app['application_id']}",
            )

            st.caption(f"Application ID: {app['application_id']}")

            if st.button("Save update", key=f"save_{app['application_id']}", use_container_width=True):
                result, err = update_application_status(
                    application_id=app["application_id"],
                    status=new_status,
                    notes=notes_input,
                    run_id=run_id,
                )
                if err:
                    st.error(f"Update failed: {err}")
                else:
                    st.success(f"Application updated to {result['status']}")
                    st.rerun()


# ---------------------------------------------------------------------------
# Setup tab — Step 1: upload resume and extract profile
# ---------------------------------------------------------------------------

def render_setup_tab():
    st.subheader("Step 1 — Upload your resume")
    st.write(
        "Upload your CV (PDF or DOCX). The backend will extract your name, email, "
        "skills, and likely job roles. These will auto-populate the search fields "
        "in the Live Monitor tab so you never have to type them manually."
    )

    uploaded = st.file_uploader(
        "Choose your resume file",
        type=["pdf", "docx"],
        help="PDF or DOCX only. The file is saved to storage/resumes/ on your machine.",
    )

    if uploaded is not None:
        file_bytes = uploaded.read()
        filename = uploaded.name

        st.info(f"Selected: **{filename}** ({len(file_bytes):,} bytes)")

        if st.button("Parse resume", type="primary", use_container_width=False):
            with st.spinner("Sending to backend parser..."):
                profile, err = parse_resume_via_api(file_bytes, filename)

            if err:
                st.error(f"Parse failed: {err}")
                st.caption(
                    "Make sure the backend is running (Start backend in the sidebar) "
                    "and that the /resume/parse endpoint is reachable."
                )
            else:
                st.session_state.resume_profile = profile
                st.session_state.resume_filename = filename
                st.success("Resume parsed successfully!")
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
            st.write(f"**Likely roles ({len(roles)}):** {', '.join(roles) if roles else '—'}")
            st.write(f"**Skills ({len(skills)}):** {', '.join(skills) if skills else '—'}")

        st.markdown("#### Resume text preview")
        st.text_area(
            "First 800 characters extracted from your file",
            value=profile.get("preview", ""),
            height=180,
            disabled=True,
        )

        # Persist email from resume as the default candidate email
        if profile.get("email") and not st.session_state.get("candidate_email_set"):
            st.session_state.candidate_email = profile["email"]
            st.session_state.candidate_email_set = True

        st.info(
            "Your profile is saved for this session. "
            "Switch to the **Live Monitor** tab — search keywords are now pre-filled from your resume."
        )
    else:
        st.caption("No profile loaded yet. Upload a resume above and click Parse resume.")


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Job Application Copilot",
        page_icon="📄",
        layout="wide",
    )

    # Session state defaults
    for key, default in [
        ("active_run_id", ""),
        ("auto_refresh", False),
        ("last_refresh_ts", time.time()),
        ("resume_profile", None),
        ("resume_filename", ""),
        ("candidate_email", ""),
        ("candidate_email_set", False),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    st.title("Job Application Copilot")
    st.caption("Upload your resume → scrape matching jobs → auto-apply. Everything in one place.")

    backend_status, backend_message = get_backend_status()

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------
    with st.sidebar:
        st.header("App Controls")
        st.write(f"**Backend status:** {backend_status}")
        st.caption(backend_message)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Start backend", use_container_width=True):
                ok, msg = start_backend()
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
                st.rerun()

        with col2:
            if st.button("Stop backend", use_container_width=True):
                ok, msg = stop_backend()
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
                st.rerun()

        st.markdown("---")

        candidate_email = st.text_input(
            "Candidate email",
            value=st.session_state.candidate_email,
            key="sidebar_email",
        )
        # Keep session state in sync with sidebar input
        st.session_state.candidate_email = candidate_email

        run_id = st.text_input("Workflow run_id (optional)", DEFAULT_RUN_ID)

        if st.session_state.resume_filename:
            st.caption(f"Resume loaded: {st.session_state.resume_filename}")
        else:
            st.caption("No resume loaded yet — go to the Setup tab.")

        st.session_state.auto_refresh = st.checkbox(
            "Auto refresh live monitor",
            value=st.session_state.auto_refresh,
        )

        if st.button("Refresh now", use_container_width=True):
            st.session_state.last_refresh_ts = time.time()
            st.rerun()

    # ------------------------------------------------------------------
    # Tabs
    # ------------------------------------------------------------------
    tab_setup, tab_monitor, tab_applications, tab_health = st.tabs(
        ["⚙️ Setup", "🔴 Live Monitor", "📋 Applications", "🩺 Backend Health"]
    )

    # ---- Setup ----
    with tab_setup:
        if backend_status != "Running":
            st.warning("Start the backend first (sidebar), then upload your resume.")
        else:
            render_setup_tab()

    # ---- Live Monitor ----
    with tab_monitor:
        if backend_status != "Running":
            st.warning("Backend is not running. Start it from the sidebar first.")
            st.stop()

        st.subheader("Automation Monitor")

        # Auto-populate keywords from parsed resume profile
        profile = st.session_state.get("resume_profile") or {}
        default_keywords = ", ".join(
            (profile.get("likely_roles") or []) + (profile.get("skills") or [])
        ) or "logistics, supply chain, operations"

        form_col1, form_col2, form_col3 = st.columns(3)
        with form_col1:
            target_keywords = st.text_input(
                "Target keywords (auto-filled from resume)",
                value=default_keywords,
            )
        with form_col2:
            target_location = st.text_input("Target location", "UK")
        with form_col3:
            max_jobs = st.number_input("Max jobs to scan", min_value=1, max_value=500, value=50, step=5)

        if not st.session_state.resume_profile:
            st.info(
                "💡 No resume loaded yet. Go to **⚙️ Setup** tab first to upload your CV — "
                "keywords will then be filled automatically from your profile."
            )

        monitor_col1, monitor_col2 = st.columns([1, 2])

        with monitor_col1:
            if st.button("Start scrape/apply run", type="primary", use_container_width=True):
                payload = {
                    "candidate_email": st.session_state.candidate_email,
                    "keywords": [x.strip() for x in target_keywords.split(",") if x.strip()],
                    "location": target_location,
                    "max_jobs": int(max_jobs),
                    "auto_apply": True,
                    "track_live": True,
                    "resume_filename": st.session_state.resume_filename or None,
                }
                result, err = start_automation(payload)
                if err:
                    st.error(err)
                else:
                    st.session_state.active_run_id = result.get("run_id", "")
                    st.success(f"Automation started. Run ID: {st.session_state.active_run_id}")
                    st.rerun()

        with monitor_col2:
            active_run_id = st.text_input(
                "Active run ID",
                value=st.session_state.active_run_id or run_id,
                key="active_run_id_input",
            )
            if active_run_id != st.session_state.active_run_id:
                st.session_state.active_run_id = active_run_id

        if st.session_state.active_run_id:
            status_data, status_err = get_automation_status(st.session_state.active_run_id)

            if status_err:
                st.info(status_err)
                st.caption("The monitor UI is ready, but the automation status endpoints may not be implemented yet.")
            else:
                state = status_data.get("status", "unknown")
                stage = status_data.get("stage", "unknown")
                progress = status_data.get("progress_percent", 0)
                scanned = status_data.get("jobs_scanned", 0)
                matched = status_data.get("jobs_matched", 0)
                applied = status_data.get("jobs_applied", 0)
                failed = status_data.get("jobs_failed", 0)
                current_url = status_data.get("current_url")
                recent_logs = status_data.get("logs", [])

                st.markdown(status_badge(state), unsafe_allow_html=True)
                st.write(f"**Current stage:** {stage}")
                st.progress(min(max(int(progress), 0), 100))

                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Jobs scanned", scanned)
                k2.metric("Matches", matched)
                k3.metric("Applied", applied)
                k4.metric("Failed", failed)

                if current_url:
                    st.write(f"**Current page:** {current_url}")

                st.markdown("#### Live event log")
                if recent_logs:
                    for log in recent_logs[-20:]:
                        st.code(str(log), language="text")
                else:
                    st.caption("No logs returned yet.")

                if st.session_state.auto_refresh and state.lower() in {"queued", "running"}:
                    time.sleep(POLL_SECONDS)
                    st.rerun()
        else:
            st.info("No active automation run selected yet.")

    # ---- Applications ----
    with tab_applications:
        if backend_status != "Running":
            st.warning("Backend is not running. Start it from the sidebar first.")
        else:
            st.subheader("Application Tracker")
            data, error = get_applications(st.session_state.candidate_email)

            if error:
                st.error(f"Error fetching applications: {error}")
            else:
                apps = data.get("applications", [])
                total = data.get("total_applications", 0)

                header1, header2 = st.columns([2, 1])
                header1.write(f"**Candidate:** {st.session_state.candidate_email}")
                header2.write(f"**Total applications:** {total}")

                render_tracker_summary(apps)

                if not apps:
                    st.info("No applications found for this candidate yet.")
                else:
                    for app in apps:
                        render_application_card(app, run_id)

    # ---- Backend Health ----
    with tab_health:
        if backend_status != "Running":
            st.warning("Backend is not running. Start it from the sidebar first.")
        else:
            st.subheader("Backend Health")

            docs_resp = safe_get(f"{API_BASE_URL}/docs", timeout=5)
            if isinstance(docs_resp, Exception):
                st.error(f"FastAPI docs check failed: {docs_resp}")
            else:
                st.success("FastAPI docs endpoint is reachable.")

            openapi_resp = safe_get(f"{API_BASE_URL}/openapi.json", timeout=5)
            if isinstance(openapi_resp, Exception):
                st.error(f"OpenAPI check failed: {openapi_resp}")
            else:
                st.success("OpenAPI schema is reachable.")

                try:
                    schema = openapi_resp.json()
                    paths = schema.get("paths", {})
                    st.write(f"**Discovered API paths:** {len(paths)}")
                    if paths:
                        st.json(sorted(paths.keys()))
                except Exception as exc:
                    st.warning(f"Could not parse OpenAPI schema: {exc}")

            st.write(f"**Python executable in use:** `{sys.executable}`")

            st.markdown("#### Notes")
            st.write(
                "A running backend only means the API server is alive. "
                "Actual scraping and auto-apply require dedicated automation endpoints and background job logic."
            )
            st.write(
                "For real-time visibility, the backend should store run progress and expose it through "
                "status endpoints that this dashboard can poll."
            )


if __name__ == "__main__":
    main()
