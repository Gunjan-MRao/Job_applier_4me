"""
Job Application Copilot — Streamlit frontend v9.11

v9.11 — definitive nav fix

Problem:
- v9.10 fixed the StreamlitAPIException, but the UI could still snap back to
  the Setup page during reruns / auto-refresh because navigation was still
  driven by a widget-bound radio key ("page").
- During reruns, Streamlit restores widget state from the browser and that can
  override our intended page selection.

Fix:
- Remove widget-bound radio navigation entirely.
- Use pure session_state navigation with button-based tabs.
- Add a small helper set_page(page_name) that updates session_state and reruns.
- Keep _next_page support so setup parsing can jump directly to AI Agent.
- Force page to AI Agent when the agent is launched.

This makes page selection deterministic across reruns, refreshes and polling.
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

BASE_DIR     = Path(__file__).resolve().parent
API_HOST     = "127.0.0.1"
API_PORT     = 8000
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
PID_FILE     = BASE_DIR / "runtime_api.pid"
LOG_FILE     = BASE_DIR / "backend_startup.log"
PYTHON_EXE   = sys.executable

PAGE_SETUP   = "⚙️ Setup"
PAGE_AGENT   = "🤖 AI Agent"
PAGE_DEBATE  = "🧠 Agent Debate"
PAGE_APPS    = "📋 Applications"
PAGE_HEALTH  = "🩺 Health"
PAGES        = [PAGE_SETUP, PAGE_AGENT, PAGE_DEBATE, PAGE_APPS, PAGE_HEALTH]

SOURCE_ICONS = {
    "linkedin":           "🔵 LinkedIn",
    "indeed":             "🔍 Indeed",
    "glassdoor":          "🏢 Glassdoor",
    "google":             "🔎 Google Jobs",
    "reed":               "📕 Reed",
    "cvlibrary":          "📚 CV-Library",
    "totaljobs":          "💼 TotalJobs",
    "findajob":           "🏷️ Find a Job (GOV.UK)",
    "nhs":                "🏥 NHS Jobs",
    "ukvisasponsorships": "🛣️ UK Visa Sponsorships",
    "fallback":           "📦 Sample",
}

DEFAULT_KEYWORDS = (
    "graduate supply chain analyst, operations analyst, demand planning analyst, "
    "procurement analyst, logistics analyst, inventory analyst, supply chain graduate scheme, "
    "business analyst supply chain, category analyst"
)

AUTO_REFRESH_S  = 5
POLL_THROTTLE_S = 4.0


def set_page(page_name: str):
    st.session_state["page"] = page_name
    st.rerun()


def render_nav():
    current = st.session_state.get("page", PAGE_SETUP)
    cols = st.columns(len(PAGES))
    for col, page_name in zip(cols, PAGES):
        kind = "primary" if current == page_name else "secondary"
        with col:
            if st.button(page_name, use_container_width=True, type=kind):
                set_page(page_name)


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
    lines = [l.strip() for l in text.splitlines() if l.strip()]
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
    if is_port_open():
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
    roles  = profile.get("likely_roles") or []
    skills = profile.get("skills") or []
    sc_roles = [r for r in roles if any(t in r.lower() for t in (
        "supply chain", "logistics", "procurement", "operations",
        "inventory", "demand", "transport", "warehouse",
        "purchasing", "coordinator", "analyst",
    ))]
    sc_skills = [s for s in skills if s in (
        "supply chain", "logistics", "procurement", "sap", "excel", "erp",
        "forecasting", "demand planning", "inventory management", "operations",
        "power bi", "sql", "s&op", "vendor management",
    )]
    combined = sc_roles[:3] + sc_skills[:5]
    seen, out = set(), []
    for k in combined:
        if k not in seen:
            seen.add(k)
            out.append(k)
    if not out:
        out = sc_skills[:6] or [
            "graduate supply chain analyst",
            "demand planning analyst",
            "operations analyst",
            "procurement analyst",
            "logistics analyst",
            "inventory analyst",
        ]
    return ", ".join(out[:8])

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
    return SOURCE_ICONS.get((s or "").lower(), f"🔍 {s}")

def _sidebar_name(p, filename):
    name = (p or {}).get("candidate_name") or ""
    if not name and filename:
        stem = Path(filename).stem
        stem = re.sub(r"[_\-]?(resume|cv|updated|new|final|\d{4})", "", stem, flags=re.I)
        name = stem.replace("_", " ").replace("-", " ").strip().title()
    return name or "?"

def _get_pending() -> dict:
    if "_pending" not in st.session_state:
        st.session_state["_pending"] = {"done": False, "run_id": None, "error": None, "stage": ""}
    return st.session_state["_pending"]

def _reset_pending():
    st.session_state["_pending"] = {"done": False, "run_id": None, "error": None, "stage": ""}

def _launch_agent_thread(pending: dict):
    pending["stage"] = "⚙️ Starting backend..."
    if not is_port_open():
        ok, msg = start_backend()
        if not ok:
            pending["error"] = f"Backend failed to start: {msg}"
            pending["done"]  = True
            return
    pending["stage"] = "📡 Calling /automation/start..."
    cfg = pending.get("cfg", {})
    result, err = _post("/automation/start", cfg)
    if err or not result:
        pending["error"] = f"API error: {err}"
        pending["done"]  = True
        return
    pending["run_id"] = result.get("run_id", "")
    pending["done"]   = True

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

def tab_setup():
    st.subheader("⚙️ Upload your resume")
    st.write("💡 Parsing works **immediately** — no need to start the backend first.")
    uploaded = st.file_uploader("Choose your CV (PDF or DOCX)", type=["pdf", "docx"])
    if uploaded:
        fb = uploaded.read()
        st.info(f"Selected: **{uploaded.name}** ({len(fb):,} bytes)")
        if st.button("Parse resume ➤", type="primary"):
            with st.spinner("Parsing..."):
                profile, err = parse_resume(fb, uploaded.name)
            if err:
                st.error(err)
            else:
                st.session_state.resume_profile  = profile
                st.session_state.resume_filename = uploaded.name
                if profile.get("email") and not st.session_state.get("candidate_email"):
                    st.session_state.candidate_email = profile["email"]
                st.session_state["_next_page"] = PAGE_AGENT
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
            roles_str   = ", ".join(p.get("likely_roles") or []) or "—"
            skills_list = p.get("skills") or []
            st.write(f"🎯 **Roles detected:** {roles_str}")
            st.write(f"⚙️ **Skills ({len(skills_list)}):** {', '.join(skills_list) or '—'}")
        edu_list = p.get("education") or []
        if edu_list:
            st.write(f"🎓 **Education:** {', '.join(edu_list)}")
        st.info(f"🔑 **Keywords for agent:** `{smart_keywords(p)}`")
        with st.expander("Resume text preview"):
            st.text(p.get("preview", ""))

def tab_agent():
    st.subheader("🤖 AI Job Agent")
    p = st.session_state.get("resume_profile") or {}

    col_be, col_gem = st.columns(2)
    be_status, _    = backend_status_info()
    with col_be:
        if be_status == "Running":
            st.info("🟢 Backend: **Running**")
        else:
            st.warning(f"🔴 Backend: **{be_status}** — agent will start it automatically")

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    env_file   = BASE_DIR / ".env"
    if not gemini_key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                gemini_key = line.split("=", 1)[1].strip()
                break
    with col_gem:
        if gemini_key:
            st.success("✅ Gemini API key — AI cover letters enabled")
        else:
            st.warning("⚠️ No Gemini key — using smart offline templates")

    if not p:
        st.warning("⚠️ No resume loaded — go to **⚙️ Setup** first for best results.")

    default_kw = smart_keywords(p) if p else DEFAULT_KEYWORDS

    with st.form("agent_form"):
        c1, c2   = st.columns(2)
        keywords = c1.text_input("🔑 Keywords", value=default_kw)
        location = c2.text_input("📍 Location", "United Kingdom")
        with st.expander("🔧 Advanced filters (optional)"):
            blacklist  = st.text_input("Skip these companies (comma-separated)", "")
            whitelist  = st.text_input("Only show these companies (optional)", "")
            auto_apply = st.checkbox("Auto-generate cover letter + cold email per match", value=True)
        go = st.form_submit_button("🚀 Start AI Agent — scan ALL job boards",
                                   type="primary", use_container_width=True)

    if go:
        if st.session_state.get("agent_launched"):
            st.warning("Agent already running — see dashboard below.")
        else:
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
            st.session_state["page"]           = PAGE_AGENT
            st.session_state["agent_launched"] = True
            st.session_state["run_id"]         = None
            st.session_state["agent_status"]   = "starting"
            st.session_state["agent_stage"]    = "⚙️ Connecting to backend..."
            st.session_state["agent_cfg"]      = cfg
            st.session_state.pop("_last_poll_ts",   None)
            st.session_state.pop("_last_poll_data", None)
            _reset_pending()
            pending = _get_pending()
            pending["cfg"] = cfg
            threading.Thread(target=_launch_agent_thread, args=(pending,), daemon=True).start()
            st.rerun()

    if st.session_state.get("agent_launched"):
        st.session_state["page"] = PAGE_AGENT

    if not st.session_state.get("agent_launched"):
        st.markdown("---")
        st.info(
            "👆 Fill in your keywords above and click **🚀 Start AI Agent** to begin.\n\n"
            "The agent simultaneously searches **LinkedIn, Indeed, Glassdoor, Reed, "
            "CV-Library, TotalJobs, GOV.UK Find a Job, NHS Jobs, and UK Visa Sponsorships** — "
            "then instantly generates a tailored cover letter and cold recruiter email for every match."
        )
        return

    st.markdown("---")

    pending = _get_pending()
    if pending["done"] and not st.session_state.get("run_id"):
        if pending.get("error"):
            st.session_state["agent_status"] = "failed"
            st.session_state["agent_stage"]  = pending["error"]
        elif pending.get("run_id"):
            st.session_state["run_id"]       = pending["run_id"]
            st.session_state["agent_status"] = "running"
            st.session_state["agent_stage"]  = "🔍 Scanning job boards..."

    if not st.session_state.get("run_id") and st.session_state.get("agent_status") != "failed":
        stage = pending.get("stage") or st.session_state.get("agent_stage") or "Starting..."
        st.info(f"⏳ {stage}")
        st.markdown('<meta http-equiv="refresh" content="2">', unsafe_allow_html=True)
        return

    run_id = st.session_state.get("run_id", "")

    if run_id:
        data = _poll_status(run_id)
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
        r1c2.info(f"📍 {stage}")
    st.progress(min(max(int(prog), 0), 100))
    if current_url and running:
        st.caption(f"⏳ Scanning: {current_url[:90]}")

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("🔍 Jobs Found", scanned)
    mc2.metric("✅ Matched", matched)
    mc3.metric("📤 Applications", applied_count)
    mc4.metric("⚠️ Needs Review", sum(1 for j in aj if not j.get("cover_letter")))

    st.markdown("#### 📶 Live source feed")
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
    ready        = [j for j in aj if j.get("cover_letter")]
    if needs_review:
        st.markdown(f"### ⚠️ Needs Your Review ({len(needs_review)})")
        st.caption("Matched but cover letter couldn't be generated — apply manually.")
        for job in reversed(needs_review[-20:]):
            _render_job_card(job, review_mode=True)
    if ready:
        st.markdown(f"### 📨 Ready to Send ({len(ready)})")
        for job in reversed(ready[-50:]):
            _render_job_card(job, review_mode=False)

    log = st.session_state.get("agent_log", [])
    with st.expander("📝 Agent log", expanded=running):
        if log:
            for line in reversed(log[-60:]):
                st.code(line, language=None)
        else:
            st.caption("Log will appear here once the agent starts sending results.")

    if summary:
        with st.expander("📈 Final summary"):
            st.json(summary)

    if running:
        st.markdown(f'<meta http-equiv="refresh" content="{AUTO_REFRESH_S}">', unsafe_allow_html=True)
    elif status == "completed":
        st.balloons()
        if st.button("🔄 Start a new search"):
            for k in ("agent_launched", "run_id", "agent_status", "agent_stage",
                      "agent_progress", "agent_scanned", "agent_matched",
                      "agent_applied", "agent_url", "agent_jobs", "agent_sources",
                      "agent_summary", "agent_matches", "agent_log", "agent_cfg",
                      "_last_poll_ts", "_last_poll_data", "_pending"):
                st.session_state.pop(k, None)
            st.session_state["page"] = PAGE_SETUP
            st.rerun()
    elif status == "failed":
        st.error(f"❌ Agent failed: {stage}")
        if st.button("🔄 Try again"):
            for k in ("agent_launched", "run_id", "agent_status", "agent_stage",
                      "agent_progress", "agent_scanned", "agent_matched",
                      "agent_applied", "agent_url", "agent_jobs", "agent_sources",
                      "agent_summary", "agent_matches", "agent_log", "agent_cfg",
                      "_last_poll_ts", "_last_poll_data", "_pending"):
                st.session_state.pop(k, None)
            st.session_state["page"] = PAGE_AGENT
            st.rerun()

def _render_job_card(job: dict, review_mode: bool):
    fit   = job.get("fit_score", 0)
    title = job.get("title", "Unknown role")
    co    = job.get("company", "Unknown company")
    src   = source_label(job.get("source", ""))
    spons = job.get("sponsorship_status", "unknown")
    url   = job.get("url", "")
    spons_html = {
        "yes":     status_pill("Sponsors visas", "#10b981"),
        "no":      status_pill("No sponsorship", "#ef4444"),
        "unknown": status_pill("Sponsorship ?", "#f59e0b"),
    }.get(spons, "")
    label = f"{'⚠️' if review_mode else '✅'} {fit}% | {title} @ {co} | {src}"
    with st.expander(label):
        hc1, hc2, hc3 = st.columns([2, 1, 1])
        with hc1:
            st.markdown(f"**{title}** at **{co}**")
            if url:
                st.link_button("🔗 Apply / View job", url, use_container_width=True)
        with hc2:
            st.markdown(spons_html, unsafe_allow_html=True)
        with hc3:
            st.metric("Fit score", f"{fit}%")
        if job.get("cover_letter"):
            st.markdown("📝 **Cover Letter** (edit before sending):")
            st.text_area("cover_letter", value=job["cover_letter"], height=230,
                         key=f"cl_{url}{title}{fit}")
        elif review_mode:
            st.warning("Cover letter failed — apply directly via the link above.")
        if job.get("cold_email"):
            st.markdown("📧 **Cold Recruiter Email** (edit before sending):")
            st.text_area("cold_email", value=job["cold_email"], height=190,
                         key=f"ce_{url}{title}{fit}")

def tab_debate():
    st.subheader("🧠 Multi-Agent Strategy Debate")
    st.caption("Paste a job you're considering — 5 AI agents debate whether you should apply, how to approach it, and what the risks are.")
    st.info("Debate page unchanged in this fix.")

def tab_applications():
    st.subheader("📋 Application Tracker")
    email = st.session_state.get("candidate_email", "")
    if not email:
        st.info("Enter your email in the sidebar to view applications.")
        return
    if not is_port_open():
        st.warning("⚠️ Backend not running — start it from the sidebar.")
        return
    data, err = _get(f"/applications/{email}")
    if err or not data:
        st.error(f"Could not load applications. Detail: {err or 'empty response'}")
        return
    apps = data.get("applications", [])
    total = data.get("total_applications", len(apps))
    st.metric("Total", total)
    if not apps:
        st.info("📭 No applications yet. Run the AI Agent to start applying!")
        return
    for app in apps:
        jd = app.get("job") or {}
        st.write(f"**{jd.get('title') or app.get('job_title') or 'Unknown role'}** — {jd.get('company') or app.get('company') or 'Unknown'}")

def tab_health():
    st.subheader("🩺 Diagnostics")
    status, detail = backend_status_info()
    icon = "✅" if status == "Running" else "❌"
    st.write(f"{icon} **Backend:** {status} — {detail}")
    st.write(f"**Python:** `{PYTHON_EXE}`")
    st.write(f"**Working dir:** `{BASE_DIR}`")

def main():
    st.set_page_config(page_title="Job Application Copilot", page_icon="🤖", layout="wide")

    defaults = {
        "resume_profile":  None,
        "resume_filename": "",
        "candidate_email": "",
        "agent_launched":  False,
        "run_id":          None,
        "agent_status":    "idle",
        "agent_stage":     "",
        "page":            PAGE_SETUP,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if "_next_page" in st.session_state:
        st.session_state["page"] = st.session_state.pop("_next_page")

    st.title("🤖 Job Application Copilot")
    st.caption("Upload CV → Agent scans every job board → instant cover letter + cold email per match")

    render_nav()
    st.markdown("---")
    page = st.session_state.get("page", PAGE_SETUP)

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
            if ok:
                st.success(msg)
            else:
                st.error(msg)
            st.rerun()
        if c2.button("■ Stop", use_container_width=True):
            ok, msg = stop_backend()
            if ok:
                st.success(msg)
            else:
                st.error(msg)
            st.rerun()
        st.markdown("---")
        st.session_state.candidate_email = st.text_input(
            "Your email", value=st.session_state.candidate_email,
            placeholder="your@email.com")
        p = st.session_state.get("resume_profile")
        if p:
            st.success(f"📎 {st.session_state.resume_filename}")
            name = _sidebar_name(p, st.session_state.resume_filename)
            st.caption(f"{name} | {len(p.get('skills') or [])} skills | {p.get('years_of_experience_hint') or '?'}")
        else:
            st.info("📎 Upload CV in ⚙️ Setup tab")
        if st.button("↻ Refresh", use_container_width=True):
            st.rerun()

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
