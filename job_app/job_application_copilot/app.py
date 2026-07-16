"""
Job Application Copilot — Streamlit frontend v6

New in v6:
- LIVE source feed: shows which board (LinkedIn/Indeed/Reed etc) is being scraped right now
- Real-time dashboard: Found / Matched / Applied / Needs Review with auto-refresh
- Each job card: apply link, cover letter, cold email, resume guidance
- Smart keywords: top 8 role-based terms auto-built from parsed CV
- Needs-review queue: jobs the agent couldn't auto-apply
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
POLL_SECONDS = 3          # fast refresh for live feel

SOURCE_ICONS = {
    "linkedin": "🔵 LinkedIn",
    "indeed": "🔍 Indeed",
    "glassdoor": "🏢 Glassdoor",
    "google": "🔎 Google Jobs",
    "reed": "📕 Reed",
    "cvlibrary": "📚 CV-Library",
    "totaljobs": "💼 TotalJobs",
    "findajob": "🏷️ Find a Job (GOV.UK)",
    "nhs": "🏥 NHS Jobs",
    "ukvisasponsorships": "🛣️ UK Visa Sponsorships",
    "fallback": "📦 Sample",
}


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
        kw = dict(cwd=str(BASE_DIR), stdout=open(LOG_FILE, "w"), stderr=subprocess.STDOUT)
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
# Resume helpers
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

def smart_keywords(profile: dict) -> str:
    """Build a focused, high-quality keyword string from the parsed profile."""
    roles = profile.get("likely_roles") or []
    skills = profile.get("skills") or []
    # Priority: most specific roles first, then high-value skills
    priority_skills = [s for s in skills if s in (
        "supply chain", "logistics", "procurement", "operations",
        "data analysis", "python", "sql", "excel", "sap", "power bi",
        "forecasting", "demand planning", "inventory management",
        "project management", "business analysis", "erp"
    )]
    combined = roles[:3] + priority_skills[:5]
    # dedupe preserving order
    seen = set()
    out = []
    for k in combined:
        if k not in seen:
            seen.add(k)
            out.append(k)
    if not out:
        out = skills[:6] or ["logistics", "supply chain", "operations"]
    return ", ".join(out[:8])


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
        AGENT["log"] = AGENT["log"][-500:]

def _agent(config):
    with AGENT_LOCK:
        AGENT.update({"running": True, "status": "starting", "run_id": None,
                      "summary": None, "top_matches": [], "applied_jobs": [],
                      "log": [], "scanned": 0, "matched": 0, "applied": 0,
                      "progress": 0, "stage": "", "current_url": "",
                      "source_counts": {}})
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

    _alog(f"Launching: {config.get('keywords')} in {config.get('location')}")
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

        applied_jobs = data.get("applied_jobs") or []
        # build per-source counts from applied jobs
        source_counts = dict(Counter(j.get("source", "unknown") for j in applied_jobs))

        with AGENT_LOCK:
            AGENT.update({
                "status":      data.get("status", "unknown"),
                "stage":       data.get("stage", ""),
                "progress":    data.get("progress_percent", 0),
                "scanned":     data.get("jobs_scanned", 0),
                "matched":     data.get("jobs_matched", 0),
                "applied":     data.get("jobs_applied", 0),
                "current_url": data.get("current_url") or "",
                "top_matches": data.get("top_matches") or [],
                "applied_jobs": applied_jobs,
                "source_counts": source_counts,
            })

        state = data.get("status", "unknown")
        stage = data.get("stage", "")
        _alog(f"{stage} | {data.get('progress_percent',0)}% | "
              f"scanned={data.get('jobs_scanned',0)} "
              f"matched={data.get('jobs_matched',0)} "
              f"applied={data.get('jobs_applied',0)}")

        if state in ("completed", "failed"):
            with AGENT_LOCK:
                AGENT.update({"running": False, "summary": data.get("result_summary")})
            _alog(f"{'Done' if state=='completed' else 'Failed'}")
            return

def launch_agent(config):
    threading.Thread(target=_agent, args=(config,), daemon=True).start()


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def badge(s, custom_color=None):
    c = custom_color or {
        "running":"#0ea5e9","completed":"#10b981","failed":"#ef4444",
        "queued":"#f59e0b","starting":"#f59e0b","stopped":"#6b7280",
        "draft":"#f59e0b","submitted":"#10b981","rejected":"#ef4444",
        "interview":"#8b5cf6","needs review":"#f97316",
    }.get((s or "").lower(), "#6b7280")
    return (f'<span style="padding:3px 12px;border-radius:999px;background:{c}22;'
            f'color:{c};font-weight:700;font-size:13px;border:1px solid {c}66">{s}</span>')

def source_label(s):
    return SOURCE_ICONS.get((s or "").lower(), f"🔍 {s}")


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
            st.write(f"🎯 **Roles detected:** {', '.join(p.get('likely_roles') or []) or '—'}")
            st.write(f"⚙️ **Skills detected ({len(p.get('skills') or [])}):** {', '.join(p.get('skills') or []) or '—'}")
        kw = smart_keywords(p)
        st.info(f"🔑 **Smart keywords that will be used:** `{kw}`")
        with st.expander("Resume text preview"):
            st.text(p.get("preview", ""))


# ---------------------------------------------------------------------------
# Tab: AI Agent  (live dashboard)
# ---------------------------------------------------------------------------

def tab_agent():
    st.subheader("🤖 AI Job Agent")

    p = st.session_state.get("resume_profile") or {}

    # Top status bar
    col_be, col_gem = st.columns(2)
    be_status, _ = backend_status_info()
    col_be.info(f"🟢 Backend: **{be_status}**" if be_status == "Running"
                else f"🔴 Backend: **{be_status}** — agent will start it automatically")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    env_file = BASE_DIR / ".env"
    if not gemini_key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                gemini_key = line.split("=", 1)[1].strip()
                break
    if gemini_key:
        col_gem.success("✅ Gemini API key — AI cover letters enabled")
    else:
        col_gem.warning("⚠️ No Gemini key — using smart offline templates")

    if not p:
        st.warning("⚠️ No resume loaded — go to **⚙️ Setup** first for best results.")

    default_kw = smart_keywords(p) if p else "supply chain, logistics, operations, procurement"

    # --- Launch form ---
    with st.form("agent_form"):
        c1, c2 = st.columns(2)
        keywords = c1.text_input("🔑 Keywords (auto-built from your CV)", value=default_kw,
                                  help="These are your best-fit job search terms. Edit freely.")
        location = c2.text_input("📍 Location", "United Kingdom")
        with st.expander("🔧 Advanced filters (optional)"):
            blacklist = st.text_input("Skip these companies (comma-separated)", "")
            whitelist = st.text_input("Only show these companies (optional)", "")
            auto_apply = st.checkbox(
                "Auto-generate cover letter + cold email per match", value=True)
        go = st.form_submit_button("🚀 Start AI Agent — scan ALL job boards",
                                   type="primary", use_container_width=True)

    if go:
        with AGENT_LOCK:
            already = AGENT.get("running", False)
        if already:
            st.warning("Agent already running — scroll down for live progress.")
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
            st.success("🤖 Agent launched! Live dashboard below.")
            time.sleep(1)
            st.rerun()

    # --- Live state ---
    with AGENT_LOCK:
        running      = AGENT.get("running", False)
        status       = AGENT.get("status", "idle")
        prog         = AGENT.get("progress", 0)
        stage        = AGENT.get("stage", "")
        log          = list(AGENT.get("log", []))
        aj           = list(AGENT.get("applied_jobs", []))
        scanned      = AGENT.get("scanned", 0)
        matched      = AGENT.get("matched", 0)
        applied      = AGENT.get("applied", 0)
        current_url  = AGENT.get("current_url", "")
        source_counts= dict(AGENT.get("source_counts", {}))
        summary      = AGENT.get("summary")

    if status == "idle":
        st.markdown("---")
        st.info("👆 Fill in your keywords above and click **🚀 Start AI Agent** to begin.\n\n"
                "The agent will simultaneously search LinkedIn, Indeed, Glassdoor, Reed, "
                "CV-Library, TotalJobs, GOV.UK Find a Job, NHS Jobs, and UK Visa Sponsorships — "
                "then instantly generate a tailored cover letter and cold recruiter email for every match.")
        return

    # =======================================================================
    # LIVE DASHBOARD
    # =======================================================================
    st.markdown("---")

    # Row 1: status + progress
    sr1c1, sr1c2 = st.columns([1, 3])
    sr1c1.markdown(f"**Status:** {badge(status)}", unsafe_allow_html=True)
    if stage:
        sr1c2.write(f"📍 **Now:** `{stage}`")
    st.progress(min(max(int(prog), 0), 100))
    if current_url and running:
        st.caption(f"⏳ Scanning: {current_url[:80]}...")

    # Row 2: big metric cards
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("🔍 Jobs Found",    scanned)
    mc2.metric("✅ Matched",        matched)
    mc3.metric("📤 Applications",  applied,
               help="Cover letter + cold email generated")
    needs_review = sum(1 for j in aj if not j.get("cover_letter"))
    mc4.metric("⚠️ Needs Review",  needs_review,
               help="Jobs matched but cover letter couldn't be generated — apply manually")

    # Row 3: live source feed
    if source_counts or running:
        st.markdown("#### 📶 Live source feed")
        all_sources = list(SOURCE_ICONS.keys())
        cols = st.columns(min(len(all_sources), 5))
        for i, src in enumerate(all_sources):
            cnt = source_counts.get(src, 0)
            icon = SOURCE_ICONS[src]
            col = cols[i % 5]
            if cnt > 0:
                col.success(f"{icon}\n\n**{cnt}** jobs")
            elif running and stage and "scrap" in stage.lower():
                col.info(f"{icon}\n\n*scanning...*")
            else:
                col.empty()

    st.markdown("---")

    # =======================================================================
    # JOB CARDS  — Needs Review first, then all matches
    # =======================================================================
    needs_review_jobs = [j for j in aj if not j.get("cover_letter")]
    ready_jobs        = [j for j in aj if j.get("cover_letter")]

    if needs_review_jobs:
        st.markdown(f"### ⚠️ Needs Your Review ({len(needs_review_jobs)})")
        st.caption("These matched your profile but the AI couldn't generate a cover letter. Apply manually.")
        for job in reversed(needs_review_jobs[-20:]):
            _render_job_card(job, review_mode=True)

    if ready_jobs:
        st.markdown(f"### 📨 Ready to Send ({len(ready_jobs)}) — live feed")
        for job in reversed(ready_jobs[-50:]):
            _render_job_card(job, review_mode=False)

    # Agent log
    with st.expander("📝 Agent log", expanded=False):
        for line in reversed(log[-50:]):
            st.code(line, language=None)

    if summary:
        with st.expander("📈 Final summary"):
            st.json(summary)

    if running:
        time.sleep(POLL_SECONDS)
        st.rerun()
    elif status == "completed":
        st.balloons()
        if st.button("🔄 Start a new search"):
            with AGENT_LOCK: AGENT.clear()
            st.rerun()


def _render_job_card(job: dict, review_mode: bool):
    fit    = job.get("fit_score", 0)
    title  = job.get("title", "Unknown role")
    co     = job.get("company", "Unknown company")
    src    = source_label(job.get("source", ""))
    spons  = job.get("sponsorship_status", "unknown")
    url    = job.get("url", "")

    spons_badge = {
        "yes":     badge("Sponsors visas",  "#10b981"),
        "no":      badge("No sponsorship",  "#ef4444"),
        "unknown": badge("Sponsorship ?",   "#f59e0b"),
    }.get(spons, "")

    label = f"{'⚠️' if review_mode else '✅'} {fit}% | {title} @ {co} | {src}"

    with st.expander(label, expanded=False):
        hc1, hc2, hc3 = st.columns([2, 1, 1])
        with hc1:
            st.markdown(f"**{title}** at **{co}**")
            if url:
                st.link_button("🔗 Apply / View job", url, use_container_width=True)
        with hc2:
            st.markdown(spons_badge, unsafe_allow_html=True)
        with hc3:
            st.metric("Fit score", f"{fit}%")

        if job.get("cover_letter"):
            st.markdown("📝 **Cover Letter** (edit before sending):")
            st.text_area("cover_letter", value=job["cover_letter"], height=230,
                         key=f"cl_{url}{title}_{fit}")
        elif review_mode:
            st.warning("Cover letter generation failed — use the job link above to apply directly.")

        if job.get("cold_email"):
            st.markdown("📧 **Cold Recruiter Email** (edit before sending):")
            st.text_area("cold_email", value=job["cold_email"], height=190,
                         key=f"ce_{url}{title}_{fit}")

        if job.get("resume_guidance"):
            with st.expander("📄 Resume tailoring tips"):
                g = job["resume_guidance"]
                if isinstance(g, dict):
                    kw = g.get("keyword_analysis", {})
                    for k in kw.get("matched_keywords") or []:
                        st.write(f"✅ {k}")
                    for k in kw.get("missing_keywords") or []:
                        st.write(f"⚠️ Add to CV: {k}")
                    for line in (g.get("summary_rewrite_guidance") or []):
                        st.write(f"• {line}")


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
                    (st.success if res else st.error)("Saved" if res else e2)
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
            with st.expander("📔 Backend startup log", expanded=True):
                st.code(log[-3000:], language="")
    st.markdown("### Package checks")
    for mod, pkg, desc in [
        ("fastapi",    "fastapi",           "Backend API"),
        ("uvicorn",    "uvicorn[standard]",  "Backend server"),
        ("pydantic",   "pydantic[email]",    "Data validation"),
        ("sqlalchemy", "sqlalchemy",         "Database"),
        ("pypdf",      "pypdf",              "PDF parsing"),
        ("docx",       "python-docx",        "DOCX parsing"),
        ("jobspy",     "python-jobspy",      "Job scraping"),
        ("bs4",        "beautifulsoup4",      "HTML scraping"),
        ("requests",   "requests",           "HTTP"),
        ("openai",     "openai",             "GPT (optional)"),
        ("anthropic",  "anthropic",          "Claude (optional)"),
        ("reportlab",  "reportlab",          "PDF export (optional)"),
    ]:
        try:
            __import__(mod)
            st.success(f"✅ `{pkg}` — {desc}")
        except ImportError:
            marker = "⚠️" if "optional" in desc else "❌"
            st.error(f"{marker} `{pkg}` NOT installed. Fix: `pip install {pkg}`")
    if status == "Running":
        data, _ = _get("/openapi.json")
        if data:
            st.write(f"**{len(data.get('paths', {}))} API routes active**")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Job Application Copilot", page_icon="🤖", layout="wide")
    for k, v in {"resume_profile": None, "resume_filename": "", "candidate_email": ""}.items():
        if k not in st.session_state: st.session_state[k] = v

    st.title("🤖 Job Application Copilot")
    st.caption("Upload CV → Agent scans every job board → instant cover letter + cold email per match")

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
            st.caption(f"{p.get('candidate_name') or '?'} | {len(p.get('skills') or [])} skills | "
                       f"{p.get('years_of_experience_hint') or '?'}")
        else:
            st.info("📎 Upload CV in ⚙️ Setup tab")
        if st.button("↻ Refresh", use_container_width=True): st.rerun()

    t1, t2, t3, t4 = st.tabs(["⚙️ Setup", "🤖 AI Agent", "📋 Applications", "🩺 Health"])
    with t1: tab_setup()
    with t2: tab_agent()
    with t3: tab_applications()
    with t4: tab_health()


if __name__ == "__main__":
    main()
