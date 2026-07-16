"""
Job Application Copilot — Streamlit frontend v4

What changed:
- max_jobs removed everywhere — scans unlimited jobs
- AI Agent tab shows live cover letters + cold emails per job as they come in
- Resume upload works without backend (local parse)
- Backend start handles spaces in Python path
- Health tab shows startup log + per-package status
"""
import os
import signal
import socket
import subprocess
import sys
import time
import threading
from collections import Counter
from io import BytesIO
from pathlib import Path

import requests
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
API_HOST = "127.0.0.1"
API_PORT = 8000
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
PID_FILE = BASE_DIR / "runtime_api.pid"
LOG_FILE = BASE_DIR / "backend_startup.log"
PYTHON_EXE = sys.executable
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
    LOG_FILE.write_text("", encoding="utf-8")
    cmd = [PYTHON_EXE, "-m", "uvicorn", "backend.main:app",
           "--host", API_HOST, "--port", str(API_PORT), "--log-level", "info"]
    try:
        kw = dict(cwd=str(BASE_DIR),
                  stdout=open(LOG_FILE, "w"), stderr=subprocess.STDOUT)
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kw)
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        for _ in range(30):
            if is_port_open():
                return True, f"Backend started (PID {proc.pid})"
            time.sleep(0.5)
        log = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-1500:] if LOG_FILE.exists() else ""
        return False, f"Backend did not respond.\n\nStartup log:\n{log}"
    except Exception as exc:
        return False, f"Could not launch: {exc}"

def stop_backend():
    pid = read_pid()
    if not is_port_open() and not process_alive(pid):
        if PID_FILE.exists(): PID_FILE.unlink()
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
    if PID_FILE.exists(): PID_FILE.unlink()
    for _ in range(10):
        if not is_port_open(): return True, "Backend stopped."
        time.sleep(0.5)
    return True, "Stop signal sent."

def backend_status_info():
    pid = read_pid()
    if is_port_open():
        label, detail = "Running", f"Listening on {API_BASE_URL}"
        if pid and process_alive(pid): detail += f" (PID {pid})"
        return label, detail
    if pid and process_alive(pid):
        return "Starting", f"Process {pid} alive, port not open yet"
    if PID_FILE.exists(): PID_FILE.unlink()
    return "Stopped", "Not running"


# ---------------------------------------------------------------------------
# Local resume parse (no backend needed)
# ---------------------------------------------------------------------------

def _extract_text_raw(file_bytes, suffix):
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            return "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(file_bytes)).pages)
        if suffix == ".docx":
            from docx import Document
            return "\n".join(p.text for p in Document(BytesIO(file_bytes)).paragraphs)
    except Exception:
        pass
    return ""

def _minimal_parse(filename, text):
    import re
    em = re.search(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", text, re.I)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    skills_kw = ["python","sql","excel","supply chain","logistics","procurement",
                 "sap","operations","forecasting","power bi","tableau","aws","azure"]
    return {
        "filename": filename,
        "candidate_name": lines[0][:60] if lines else None,
        "email": em.group(0) if em else None,
        "phone": None, "skills": [s for s in skills_kw if s in text.lower()],
        "likely_roles": [], "years_of_experience_hint": None,
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
        try: tmp_path.unlink()
        except Exception: pass

def parse_resume(file_bytes, filename):
    if is_port_open():
        try:
            r = requests.post(f"{API_BASE_URL}/resume/parse",
                              files={"file": (filename, file_bytes, "application/octet-stream")},
                              timeout=30)
            r.raise_for_status()
            return r.json(), None
        except Exception:
            pass
    return parse_resume_local(file_bytes, filename)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get(path, timeout=10):
    try:
        r = requests.get(f"{API_BASE_URL}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

def _post(path, payload, timeout=60):
    try:
        r = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

def _patch(path, payload, timeout=10):
    try:
        r = requests.patch(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# AI Agent background thread
# ---------------------------------------------------------------------------

AGENT: dict = {}
AGENT_LOCK = threading.Lock()

def _alog(msg):
    with AGENT_LOCK:
        AGENT.setdefault("log", []).append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        AGENT["log"] = AGENT["log"][-300:]

def _agent(config):
    with AGENT_LOCK:
        AGENT.update({"running": True, "status": "starting", "run_id": None,
                      "summary": None, "top_matches": [], "applied_jobs": [],
                      "log": [], "scanned": 0, "matched": 0, "applied": 0,
                      "progress": 0, "stage": ""})

    _alog("Agent started.")
    if not is_port_open():
        _alog("Starting backend...")
        ok, msg = start_backend()
        if not ok:
            _alog(f"FAILED: {msg}")
            with AGENT_LOCK: AGENT.update({"running": False, "status": "failed"})
            return
        _alog(f"Backend up. {msg}")
    else:
        _alog("Backend already running.")

    _alog(f"Launching run: {config.get('keywords')} in {config.get('location')} — scanning ALL jobs")
    with AGENT_LOCK: AGENT["status"] = "running"

    result, err = _post("/automation/start", config)
    if err or not result:
        _alog(f"Failed to start run: {err}")
        with AGENT_LOCK: AGENT.update({"running": False, "status": "failed"})
        return

    run_id = result.get("run_id", "")
    with AGENT_LOCK: AGENT["run_id"] = run_id
    _alog(f"Run ID: {run_id}")

    retries = 0
    while True:
        time.sleep(POLL_SECONDS)
        data, poll_err = _get(f"/automation/status/{run_id}")
        if poll_err:
            retries += 1
            _alog(f"Poll error {retries}/5: {poll_err}")
            if retries >= 5:
                with AGENT_LOCK: AGENT.update({"running": False, "status": "failed"})
                return
            continue
        retries = 0

        state   = data.get("status", "unknown")
        stage   = data.get("stage", "")
        prog    = data.get("progress_percent", 0)
        scanned = data.get("jobs_scanned", 0)
        matched = data.get("jobs_matched", 0)
        applied = data.get("jobs_applied", 0)
        applied_jobs = data.get("applied_jobs") or []
        top     = data.get("top_matches") or (data.get("result_summary") or {}).get("top_matches") or []

        with AGENT_LOCK:
            AGENT.update({"status": state, "stage": stage, "progress": prog,
                          "scanned": scanned, "matched": matched, "applied": applied,
                          "top_matches": top, "applied_jobs": applied_jobs})

        _alog(f"{stage} | {prog}% | scanned={scanned} matched={matched} applied={applied}")

        if state in ("completed", "failed"):
            with AGENT_LOCK:
                AGENT.update({"running": False,
                              "summary": data.get("result_summary")})
            _alog(f"✅ {'Done' if state=='completed' else 'Failed'}: {scanned} scanned, {applied} processed")
            if top:
                for m in top[:5]:
                    _alog(f"  ★ {m.get('title')} @ {m.get('company')} — {m.get('fit_score')}%")
            return

def launch_agent(config):
    threading.Thread(target=_agent, args=(config,), daemon=True).start()


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def badge(s):
    c = {"running":"#0ea5e9","completed":"#10b981","failed":"#ef4444",
         "queued":"#f59e0b","starting":"#f59e0b","stopped":"#6b7280",
         "draft":"#f59e0b","submitted":"#10b981","rejected":"#ef4444","interview":"#8b5cf6"
         }.get((s or "").lower(), "#6b7280")
    return (f'<span style="padding:3px 12px;border-radius:999px;background:{c}22;'
            f'color:{c};font-weight:700;font-size:13px;border:1px solid {c}66">{s}</span>')


# ---------------------------------------------------------------------------
# Tab: Setup
# ---------------------------------------------------------------------------

def tab_setup():
    st.subheader("⚙️ Upload your resume")
    st.write("💡 Parsing works **immediately** — no need to start the backend first.")
    uploaded = st.file_uploader("Choose your CV (PDF or DOCX)", type=["pdf","docx"])
    if uploaded:
        fb = uploaded.read()
        st.info(f"Selected: **{uploaded.name}** ({len(fb):,} bytes)")
        if st.button("Parse resume ➤", type="primary"):
            with st.spinner("Parsing..."):
                profile, err = parse_resume(fb, uploaded.name)
            if err:
                st.error(err)
            else:
                st.session_state.resume_profile = profile
                st.session_state.resume_filename = uploaded.name
                if profile.get("email") and not st.session_state.get("candidate_email"):
                    st.session_state.candidate_email = profile["email"]
                st.success("✅ Parsed! Switch to **🤖 AI Agent** to start.")
                st.rerun()

    p = st.session_state.get("resume_profile")
    if p:
        st.markdown("### 📌 Extracted profile")
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"👤 **Name:** {p.get('candidate_name') or '—'}")
            st.write(f"📧 **Email:** {p.get('email') or '—'}")
            st.write(f"💼 **Experience:** {p.get('years_of_experience_hint') or '—'}")
        with c2:
            st.write(f"🎯 **Roles ({len(p.get('likely_roles') or [])}):** {', '.join(p.get('likely_roles') or []) or '—'}")
            st.write(f"⚙️ **Skills ({len(p.get('skills') or [])}):** {', '.join(p.get('skills') or []) or '—'}")
        with st.expander("Resume text preview"):
            st.text(p.get("preview", ""))


# ---------------------------------------------------------------------------
# Tab: AI Agent
# ---------------------------------------------------------------------------

def tab_agent():
    st.subheader("🤖 AI Agent")
    st.write(
        "One click — the agent starts the backend if needed, scrapes **every job** from "
        "LinkedIn / Indeed / Glassdoor / Reed / NHS / GOV.UK and more (no cap), "
        "scores each one against your resume, and for every match **immediately** generates "
        "a tailored resume, a cover letter, and a personalised cold email to the recruiter."
    )

    p = st.session_state.get("resume_profile") or {}
    if not p:
        st.warning("⚠️ No resume loaded — go to **⚙️ Setup** first for best results.")

    default_kw = ", ".join((p.get("likely_roles") or []) + (p.get("skills") or [])
                           ) or "logistics, supply chain, operations"

    with st.form("agent_form"):
        c1, c2 = st.columns(2)
        keywords = c1.text_input("Keywords (auto-filled from your CV)", value=default_kw)
        location = c2.text_input("Location", "United Kingdom")
        with st.expander("🔧 Advanced filters"):
            blacklist = st.text_input("Skip these companies (comma-separated)", "")
            whitelist = st.text_input("Only apply to these companies (optional)", "")
            auto_apply = st.checkbox(
                "Auto-generate cover letter + cold email per match", value=True)
        go = st.form_submit_button("🚀 Start AI Agent — scan ALL jobs",
                                   type="primary", use_container_width=True)

    if go:
        with AGENT_LOCK:
            already = AGENT.get("running", False)
        if already:
            st.warning("Agent already running — scroll down to see live progress.")
        else:
            cfg = {
                "candidate_email": st.session_state.get("candidate_email") or "user@example.com",
                "keywords": [x.strip() for x in keywords.split(",") if x.strip()],
                "location": location,
                "auto_apply": auto_apply,
                "track_live": True,
                "resume_filename": st.session_state.get("resume_filename") or None,
                "resume_profile": p or None,
                "company_blacklist": [x.strip() for x in blacklist.split(",") if x.strip()],
                "company_whitelist": [x.strip() for x in whitelist.split(",") if x.strip()],
            }
            with AGENT_LOCK: AGENT.clear()
            launch_agent(cfg)
            st.success("🤖 Agent launched! Live updates below.")
            time.sleep(1)
            st.rerun()

    # Live status
    with AGENT_LOCK:
        running   = AGENT.get("running", False)
        status    = AGENT.get("status", "idle")
        prog      = AGENT.get("progress", 0)
        stage     = AGENT.get("stage", "")
        log       = list(AGENT.get("log", []))
        matches   = list(AGENT.get("top_matches", []))
        aj        = list(AGENT.get("applied_jobs", []))
        scanned   = AGENT.get("scanned", 0)
        matched   = AGENT.get("matched", 0)
        applied   = AGENT.get("applied", 0)
        summary   = AGENT.get("summary")

    if status == "idle":
        return

    st.markdown("---")
    st.markdown(f"**Status:** {badge(status)}", unsafe_allow_html=True)
    if stage: st.write(f"**Stage:** `{stage}`")
    st.progress(min(max(int(prog), 0), 100))

    m1, m2, m3 = st.columns(3)
    m1.metric("🔍 Scanned", scanned)
    m2.metric("✅ Matched", matched)
    m3.metric("📤 Processed", applied)

    # Applied jobs — show cover letter + cold email inline
    if aj:
        st.markdown(f"### 📨 Processed jobs ({len(aj)}) — live feed")
        for job in reversed(aj[-30:]):   # most recent first
            with st.expander(
                f"★ {job.get('fit_score',0)}% | {job.get('title','?')} @ {job.get('company','?')} "
                f"| {job.get('sponsorship_status','')} | {job.get('source','')}",
                expanded=False
            ):
                if job.get("url"):
                    st.link_button("🔗 View job", job["url"])

                if job.get("cover_letter"):
                    st.markdown("**📝 Cover Letter:**")
                    st.text_area("Cover letter", value=job["cover_letter"],
                                 height=220, disabled=False,
                                 key=f"cl_{job.get('url','')}{job.get('title','')}")

                if job.get("cold_email"):
                    st.markdown("**📧 Cold Email to Recruiter:**")
                    st.text_area("Cold email", value=job["cold_email"],
                                 height=180, disabled=False,
                                 key=f"ce_{job.get('url','')}{job.get('title','')}")

                if job.get("resume_guidance"):
                    with st.expander("📄 Resume tailoring guidance"):
                        g = job["resume_guidance"]
                        if isinstance(g, dict):
                            kw = g.get("keyword_analysis", {})
                            if kw.get("matched_keywords"):
                                st.write(f"✅ Matched keywords: {', '.join(kw['matched_keywords'])}")
                            if kw.get("missing_keywords"):
                                st.write(f"⚠️ Missing keywords: {', '.join(kw['missing_keywords'])}")
                            for line in (g.get("summary_rewrite_guidance") or []):
                                st.write(f"• {line}")

    with st.expander("📝 Agent log", expanded=running):
        for line in reversed(log[-40:]):
            st.code(line, language=None)

    if summary:
        with st.expander("📈 Final summary"):
            st.json(summary)

    if running:
        time.sleep(POLL_SECONDS)
        st.rerun()
    elif status == "completed":
        if st.button("🔄 Start a new run"):
            with AGENT_LOCK: AGENT.clear()
            st.rerun()


# ---------------------------------------------------------------------------
# Tab: Applications
# ---------------------------------------------------------------------------

def tab_applications():
    st.subheader("📋 Application Tracker")
    email = st.session_state.get("candidate_email", "")
    if not email:
        st.info("Enter your email in the sidebar.")
        return
    if not is_port_open():
        st.warning("Start the backend first.")
        return
    data, err = _get(f"/applications/{email}")
    if err or not data:
        st.info("No applications yet or backend error.")
        return
    apps = data.get("applications", [])
    counts = Counter((a.get("status") or "").lower() for a in apps)
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Total", len(apps)); c2.metric("Draft", counts.get("draft",0))
    c3.metric("Submitted", counts.get("submitted",0)); c4.metric("Interview", counts.get("interview",0))
    c5.metric("Rejected", counts.get("rejected",0))
    for app in apps:
        with st.container(border=True):
            ca, cb, cc = st.columns([2,2,2])
            with ca:
                st.markdown(f"**{app['job']['title']}**")
                st.write(app['job']['company'])
                if app['job'].get('url'): st.link_button("View", app['job']['url'])
            with cb:
                st.markdown(badge(app['status']), unsafe_allow_html=True)
                st.caption(f"Updated: {app['updated_at']}")
            with cc:
                opts = ["draft","ready","submitted","interview","rejected"]
                ns = st.selectbox("Status", opts,
                    index=opts.index(app['status']) if app['status'] in opts else 0,
                    key=f"s_{app['application_id']}")
                notes = st.text_input("Notes", value=app.get("notes") or "",
                                      key=f"n_{app['application_id']}")
                if st.button("Save", key=f"sv_{app['application_id']}"):
                    res, e2 = _patch(f"/applications/{app['application_id']}/status",
                                     {"status": ns, "notes": notes or None, "run_id": None})
                    (st.success if res else st.error)(f"Saved" if res else e2)
                    if res: st.rerun()


# ---------------------------------------------------------------------------
# Tab: Health
# ---------------------------------------------------------------------------

def tab_health():
    st.subheader("🩺 Diagnostics")
    status, detail = backend_status_info()
    icon = "✅" if status == "Running" else "❌"
    st.write(f"{icon} **Backend:** {status} — {detail}")
    st.write(f"**Python:** `{PYTHON_EXE}`")
    st.write(f"**Working dir:** `{BASE_DIR}`")

    if status != "Running" and LOG_FILE.exists():
        log = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        if log.strip():
            with st.expander("📔 Backend startup log — this tells you exactly what crashed",
                             expanded=True):
                st.code(log[-3000:], language="")

    st.markdown("### Package checks")
    for mod, pkg, desc in [
        ("fastapi",    "fastapi",           "Backend API framework"),
        ("uvicorn",    "uvicorn[standard]",  "Backend server"),
        ("pydantic",   "pydantic",           "Data validation"),
        ("sqlalchemy", "sqlalchemy",         "Database ORM"),
        ("pypdf",      "pypdf",              "PDF resume parsing"),
        ("docx",       "python-docx",        "DOCX resume parsing"),
        ("jobspy",     "python-jobspy",      "Job scraping (LinkedIn/Indeed etc)"),
        ("bs4",        "beautifulsoup4",      "HTML job board scraping"),
        ("requests",   "requests",           "HTTP requests"),
        ("openai",     "openai",             "GPT-4o-mini cover letters (optional)"),
        ("anthropic",  "anthropic",          "Claude cover letters (optional)"),
        ("reportlab",  "reportlab",          "PDF export (optional)"),
    ]:
        try:
            __import__(mod)
            st.success(f"✅ `{pkg}` — {desc}")
        except ImportError:
            marker = "⚠️" if "optional" in desc else "❌"
            st.error(f"{marker} `{pkg}` NOT installed — {desc}. Fix: `pip install {pkg}`")

    if status == "Running":
        data, _ = _get("/openapi.json")
        if data:
            paths = sorted(data.get("paths", {}).keys())
            st.write(f"**{len(paths)} API routes active**")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Job Application Copilot",
                       page_icon="🤖", layout="wide")
    for k, v in {"resume_profile": None, "resume_filename": "",
                 "candidate_email": ""}.items():
        if k not in st.session_state: st.session_state[k] = v

    st.title("🤖 Job Application Copilot")
    st.caption("Upload CV → Agent scans every job → instant cover letter + cold email per match")

    status, detail = backend_status_info()

    with st.sidebar:
        st.header("🔧 Controls")
        color = "green" if status == "Running" else "red"
        st.markdown(f"**Backend:** :{color}[{status}]")
        st.caption(detail)
        c1, c2 = st.columns(2)
        if c1.button("▶ Start", use_container_width=True):
            with st.spinner("Starting..."):
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
        p = st.session_state.get("resume_profile")
        if p:
            st.success(f"📎 {st.session_state.resume_filename}")
            st.caption(f"{p.get('candidate_name') or '?'} | "
                       f"{len(p.get('skills') or [])} skills")
        else:
            st.info("📎 Upload CV in ⚙️ Setup")
        if st.button("↻ Refresh", use_container_width=True): st.rerun()

    t1, t2, t3, t4 = st.tabs(["⚙️ Setup", "🤖 AI Agent",
                                "📋 Applications", "🩺 Health"])
    with t1: tab_setup()
    with t2: tab_agent()
    with t3: tab_applications()
    with t4: tab_health()


if __name__ == "__main__":
    main()
