import os
import signal
import socket
import subprocess
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

CONDA_BASE_PYTHON = r"C:\Users\User\anaconda3\Anaconda\python.exe"
BACKEND_APP_IMPORT = "backend.main:app"

DEFAULT_EMAIL = "bindu.kp11@gmail.com"
DEFAULT_RUN_ID = ""

POLL_SECONDS = 3


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

    if not Path(CONDA_BASE_PYTHON).exists():
        return False, f"Python not found: {CONDA_BASE_PYTHON}"

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


def safe_get(url: str, timeout: int = 10):
    try:
        r = requests.get(url, timeout=timeout)
        return r
    except Exception as exc:
        return exc


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


def main():
    st.set_page_config(
        page_title="Job Application Copilot",
        page_icon="📄",
        layout="wide",
    )

    if "active_run_id" not in st.session_state:
        st.session_state.active_run_id = ""
    if "auto_refresh" not in st.session_state:
        st.session_state.auto_refresh = False
    if "last_refresh_ts" not in st.session_state:
        st.session_state.last_refresh_ts = time.time()

    st.title("Job Application Copilot")
    st.caption("Real-time dashboard for job scraping, application tracking, and backend control.")

    backend_status, backend_message = get_backend_status()

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

        candidate_email = st.text_input("Candidate email", DEFAULT_EMAIL)
        run_id = st.text_input("Workflow run_id (optional)", DEFAULT_RUN_ID)

        st.session_state.auto_refresh = st.checkbox(
            "Auto refresh live monitor",
            value=st.session_state.auto_refresh,
        )

        if st.button("Refresh now", use_container_width=True):
            st.session_state.last_refresh_ts = time.time()
            st.rerun()

    if backend_status != "Running":
        st.warning("Backend is not running. Start it from the sidebar first.")
        st.stop()

    tab1, tab2, tab3 = st.tabs(["Live Monitor", "Applications", "Backend Health"])

    with tab1:
        st.subheader("Automation Monitor")

        form_col1, form_col2, form_col3 = st.columns(3)
        with form_col1:
            target_keywords = st.text_input("Target keywords", "logistics, supply chain, operations")
        with form_col2:
            target_location = st.text_input("Target location", "UK")
        with form_col3:
            max_jobs = st.number_input("Max jobs to scan", min_value=1, max_value=500, value=50, step=5)

        monitor_col1, monitor_col2 = st.columns([1, 2])

        with monitor_col1:
            if st.button("Start scrape/apply run", type="primary", use_container_width=True):
                payload = {
                    "candidate_email": candidate_email,
                    "keywords": [x.strip() for x in target_keywords.split(",") if x.strip()],
                    "location": target_location,
                    "max_jobs": int(max_jobs),
                    "auto_apply": True,
                    "track_live": True,
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

        st.markdown("#### What you should see in real time")
        st.write(
            "- Current stage, for example: searching jobs, opening job page, screening eligibility, filling form, submitting."
        )
        st.write("- Live counters for scanned jobs, matched jobs, applications submitted, and failures.")
        st.write("- A recent log feed so you can see each step happen instead of guessing.")

    with tab2:
        st.subheader("Application Tracker")
        data, error = get_applications(candidate_email)

        if error:
            st.error(f"Error fetching applications: {error}")
        else:
            apps = data.get("applications", [])
            total = data.get("total_applications", 0)

            header1, header2 = st.columns([2, 1])
            header1.write(f"**Candidate:** {candidate_email}")
            header2.write(f"**Total applications:** {total}")

            render_tracker_summary(apps)

            if not apps:
                st.info("No applications found for this candidate yet.")
            else:
                for app in apps:
                    render_application_card(app, run_id)

    with tab3:
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

        st.markdown("#### Notes")
        st.write(
            "A running backend only means the API server is alive. Actual scraping and auto-apply require dedicated automation endpoints and background job logic."
        )
        st.write(
            "For real-time visibility, the backend should store run progress and expose it through status endpoints that this dashboard can poll."
        )


if __name__ == "__main__":
    main()