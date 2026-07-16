"""
Job Application Copilot — Streamlit frontend v9.6

v9.6 — throttled polling (fixes burst-hammer on /automation/status)
  Root cause of 50+ status requests per minute:
  `<meta http-equiv="refresh">` fires a browser reload every N seconds,
  but Streamlit also triggers internal reruns (widget interactions,
  session_state writes, etc.).  When both fire close together the status
  endpoint gets hit in rapid bursts (20+ per second seen in logs).

  Fix: lightweight time-based gate.  _poll_status() now checks
  `st.session_state["_last_poll_ts"]` and skips the HTTP call if the
  last poll was less than POLL_THROTTLE_S seconds ago, returning the
  cached payload instead.  The meta-refresh interval is raised to 5 s so
  the UI still updates promptly but the backend only sees ~1 req/5 s.

v9.5 — complete dashboard polling rewrite
  Root cause of 'no dashboard' across all previous versions:
  _AGENT module-level dict + background thread pattern is unreliable
  with Streamlit's rerun model. _sync_agent_state() could copy a stale
  'idle' value before the thread updated _AGENT, causing the dashboard
  guard to fire every single rerun.

  Fix: session_state is now the single source of truth.
  - agent_launched flag (persists across reruns) controls dashboard visibility
  - run_id stored in session_state once backend responds
  - Every rerun polls /automation/status directly (synchronous, fast)
  - No race condition possible: poll happens in main thread before render
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

# Browser meta-refresh interval while the agent is running (seconds).
# Raised from 3 → 5 so the browser doesn't trigger extra Streamlit reruns
# that would otherwise stack with internal reruns and hammer the status endpoint.
AUTO_REFRESH_S = 5

# Minimum gap between real HTTP calls to /automation/status.
# Any Streamlit rerun that lands within this window returns the cached payload.
POLL_THROTTLE_S = 4.0


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


# ---------------------------------------------------------------------------
# HTTP helpers
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
    return SOURCE_ICONS.get((s or "").lower(), f"🔍 {s}")

def _sidebar_name(p, filename):
    name = (p or {}).get("candidate_name") or ""
    if not name and filename:
        stem = Path(filename).stem
        stem = re.sub(r"[_\-]?(resume|cv|updated|new|final|\d{4})", "", stem, flags=re.I)
        name = stem.replace("_", " ").replace("-", " ").strip().title()
    return name or "?"


# ---------------------------------------------------------------------------
# Agent launch — runs entirely on background thread so UI stays responsive
# ---------------------------------------------------------------------------

def _launch_agent_thread(cfg: dict):
    """Background thread: start backend if needed, call /automation/start,
    then store run_id into session_state via a shared plain dict.
    All Streamlit session_state writes happen only in the main thread
    (picked up on next rerun via _PENDING)."""
    global _PENDING
    _PENDING["stage"] = "⚙️ Starting backend..."
    if not is_port_open():
        ok, msg = start_backend()
        if not ok:
            _PENDING["error"] = f"Backend failed to start: {msg}"
            _PENDING["done"]  = True
            return

    _PENDING["stage"] = "📡 Calling /automation/start..."
    result, err = _post("/automation/start", cfg)
    if err or not result:
        _PENDING["error"] = f"API error: {err}"
        _PENDING["done"]  = True
        return

    _PENDING["run_id"] = result.get("run_id", "")
    _PENDING["done"]   = True


# Module-level dict for inter-thread communication (no Streamlit calls)
_PENDING: dict = {"done": False, "run_id": None, "error": None, "stage": ""}


def _reset_pending():
    global _PENDING
    _PENDING = {"done": False, "run_id": None, "error": None, "stage": ""}


# ---------------------------------------------------------------------------
# Core polling — throttled to at most 1 real HTTP call per POLL_THROTTLE_S
# ---------------------------------------------------------------------------

def _poll_status(run_id: str) -> dict:
    """Synchronous poll of /automation/status/{run_id}.

    Throttled: if the last successful poll was less than POLL_THROTTLE_S ago,
    the cached payload is returned immediately without an HTTP call.
    Returns the status dict or an error dict.
    """
    now = time.monotonic()
    last_ts    = st.session_state.get("_last_poll_ts", 0.0)
    cached     = st.session_state.get("_last_poll_data")

    if cached is not None and (now - last_ts) < POLL_THROTTLE_S:
        # Still within throttle window — return cached data, no HTTP call
        return cached

    data, err = _get(f"/automation/status/{run_id}", timeout=8)
    if err or not data:
        return {"status": "unknown", "stage": f"Poll error: {err}"}

    st.session_state["_last_poll_ts"]   = now
    st.session_state["_last_poll_data"] = data
    return data


# ---------------------------------------------------------------------------
# Multi-agent strategy helpers
# ---------------------------------------------------------------------------

AGENT_PROVIDER_COLOURS = {
    "gemini":        ("#4285F4", "🔵", "Gemini 1.5 Flash"),
    "huggingface":   ("#FF6B00", "🟠", "Mistral-7B (HuggingFace)"),
    "openai":        ("#10a37f", "🟢", "GPT-4o-mini"),
    "anthropic":     ("#6b46c1", "🟣", "Claude Haiku"),
    "reddit_oracle": ("#FF4500", "🔴", "Reddit Oracle (Rule-based)"),
}

TIER_STYLE = {
    "tier1": ("#10b981", "🏆 Tier 1 — GOV.UK verified + actively sponsoring"),
    "tier2": ("#f59e0b", "✅ Tier 2 — GOV.UK verified sponsor licence"),
    "tier3": ("#ef4444", "⚠️  Tier 3 — Not on GOV.UK register — HIGH RISK"),
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


# ---------------------------------------------------------------------------
# Tab: Setup
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tab: AI Agent  (throttled polling architecture)
# ---------------------------------------------------------------------------

def tab_agent():
    st.subheader("🤖 AI Job Agent")
    p = st.session_state.get("resume_profile") or {}

    # ── Backend / API key status row ──────────────────────────────────────
    col_be, col_gem = st.columns(2)
    be_status, _   = backend_status_info()
    col_be.info("🟢 Backend: **Running**") if be_status == "Running" else \
        col_be.warning(f"🔴 Backend: **{be_status}** — agent will start it automatically")

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    env_file   = BASE_DIR / ".env"
    if not gemini_key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("GEMINI_API_KEY="):
                gemini_key = line.split("=", 1)[1].strip()
                break
    col_gem.success("✅ Gemini API key — AI cover letters enabled") if gemini_key else \
        col_gem.warning("⚠️ No Gemini key — using smart offline templates")

    if not p:
        st.warning("⚠️ No resume loaded — go to **⚙️ Setup** first for best results.")

    default_kw = smart_keywords(p) if p else DEFAULT_KEYWORDS

    # ── Launch form ───────────────────────────────────────────────────────
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

    # ── Handle launch ─────────────────────────────────────────────────────
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
            # Mark as launched FIRST so the dashboard shows on this rerun
            st.session_state["agent_launched"] = True
            st.session_state["run_id"]         = None
            st.session_state["agent_status"]   = "starting"
            st.session_state["agent_stage"]    = "⚙️ Connecting to backend..."
            st.session_state["agent_cfg"]      = cfg
            # Clear poll cache so first real poll fires immediately
            st.session_state.pop("_last_poll_ts",   None)
            st.session_state.pop("_last_poll_data", None)
            _reset_pending()
            threading.Thread(
                target=_launch_agent_thread, args=(cfg,), daemon=True
            ).start()

    # ── Nothing launched yet ──────────────────────────────────────────────
    if not st.session_state.get("agent_launched"):
        st.markdown("---")
        st.info(
            "👆 Fill in your keywords above and click **🚀 Start AI Agent** to begin.\n\n"
            "The agent simultaneously searches **LinkedIn, Indeed, Glassdoor, Reed, "
            "CV-Library, TotalJobs, GOV.UK Find a Job, NHS Jobs, and UK Visa Sponsorships** — "
            "then instantly generates a tailored cover letter and cold recruiter email for every match."
        )
        return

    # ── Dashboard ─────────────────────────────────────────────────────────
    st.markdown("---")

    # Pick up run_id from background thread if it just finished starting
    if _PENDING["done"] and not st.session_state.get("run_id"):
        if _PENDING.get("error"):
            st.session_state["agent_status"] = "failed"
            st.session_state["agent_stage"]  = _PENDING["error"]
        elif _PENDING.get("run_id"):
            st.session_state["run_id"]       = _PENDING["run_id"]
            st.session_state["agent_status"] = "running"
            st.session_state["agent_stage"]  = "🔍 Scanning job boards..."

    # Show live stage while still connecting (no run_id yet)
    if not st.session_state.get("run_id") and st.session_state.get("agent_status") != "failed":
        stage = _PENDING.get("stage") or st.session_state.get("agent_stage") or "Starting..."
        st.info(f"⏳ {stage}")
        # Auto-refresh every 2 s while connecting (short window, no run_id to poll)
        st.markdown(
            f'<meta http-equiv="refresh" content="2">',
            unsafe_allow_html=True,
        )
        return

    run_id = st.session_state.get("run_id", "")

    # ── Throttled poll (main thread, at most 1 HTTP call per POLL_THROTTLE_S) ──
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

    # ── Status bar ────────────────────────────────────────────────────────
    r1c1, r1c2 = st.columns([1, 3])
    r1c1.markdown(f"**Status:** {status_pill(status)}", unsafe_allow_html=True)
    if stage:
        r1c2.info(f"📍 {stage}")
    st.progress(min(max(int(prog), 0), 100))
    if current_url and running:
        st.caption(f"⏳ Scanning: {current_url[:90]}")

    # ── Metrics ───────────────────────────────────────────────────────────
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("🔍 Jobs Found",   scanned)
    mc2.metric("✅ Matched",       matched)
    mc3.metric("📤 Applications", applied_count)
    mc4.metric("⚠️ Needs Review",  sum(1 for j in aj if not j.get("cover_letter")))

    # ── Live source feed ──────────────────────────────────────────────────
    st.markdown("#### 📶 Live source feed")
    source_cols = st.columns(len(SOURCE_ICONS))
    for i, (src, icon) in enumerate(SOURCE_ICONS.items()):
        cnt = source_counts.get(src, 0)
        with source_cols[i]:
            if cnt > 0:   st.success(f"{icon}\n\n**{cnt}**")
            elif running: st.info(f"{icon}\n\n*...*")
            else:         st.caption(icon)

    st.markdown("---")

    # ── Job cards ─────────────────────────────────────────────────────────
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

    # ── Agent log expander ────────────────────────────────────────────────
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

    # ── Auto-refresh / finish buttons ─────────────────────────────────────
    if running:
        st.markdown(
            f'<meta http-equiv="refresh" content="{AUTO_REFRESH_S}">',
            unsafe_allow_html=True,
        )
    elif status == "completed":
        st.balloons()
        if st.button("🔄 Start a new search"):
            for k in ("agent_launched", "run_id", "agent_status", "agent_stage",
                      "agent_progress", "agent_scanned", "agent_matched",
                      "agent_applied", "agent_url", "agent_jobs", "agent_sources",
                      "agent_summary", "agent_matches", "agent_log", "agent_cfg",
                      "_last_poll_ts", "_last_poll_data"):
                st.session_state.pop(k, None)
            _reset_pending()
            st.rerun()
    elif status == "failed":
        st.error(f"❌ Agent failed: {stage}")
        if st.button("🔄 Try again"):
            for k in ("agent_launched", "run_id", "agent_status", "agent_stage",
                      "agent_progress", "agent_scanned", "agent_matched",
                      "agent_applied", "agent_url", "agent_jobs", "agent_sources",
                      "agent_summary", "agent_matches", "agent_log", "agent_cfg",
                      "_last_poll_ts", "_last_poll_data"):
                st.session_state.pop(k, None)
            _reset_pending()
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
        "unknown": status_pill("Sponsorship ?",  "#f59e0b"),
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
        if job.get("resume_guidance"):
            with st.expander("📄 Resume tailoring tips"):
                g = job["resume_guidance"]
                if isinstance(g, dict):
                    for k in (g.get("keyword_analysis") or {}).get("matched_keywords") or []:
                        st.write(f"✅ {k}")
                    for k in (g.get("keyword_analysis") or {}).get("missing_keywords") or []:
                        st.write(f"⚠️ Add to CV: {k}")
                    for line in g.get("summary_rewrite_guidance") or []:
                        st.write(f"• {line}")


# ---------------------------------------------------------------------------
# Tab: Agent Debate
# ---------------------------------------------------------------------------

def tab_debate():
    st.subheader("🧠 Multi-Agent Strategy Debate")
    st.caption(
        "Paste a job you're considering — 5 AI agents debate whether you should apply, "
        "how to approach it, and what the risks are."
    )
    run_debate_fn, hiring_window_fn = _import_strategy()
    if hiring_window_fn:
        try:
            win = hiring_window_fn()
            wc  = "#10b981" if win["score"] >= 70 else ("#f59e0b" if win["score"] >= 40 else "#ef4444")
            st.markdown(
                f'<div style="padding:8px 16px;border-radius:8px;background:{wc}22;'
                f'border:1px solid {wc}66;margin-bottom:12px">📅 '
                f'<strong>Current hiring window ({win["month"]}):</strong> '
                f'<span style="color:{wc}">{win["advice"]}</span></div>',
                unsafe_allow_html=True)
        except Exception:
            pass
    if run_debate_fn is None:
        st.error("❌ Could not import sponsor_strategy.py.")
        return
    profile = st.session_state.get("resume_profile") or {}
    if not profile:
        st.warning("⚠️ No resume loaded — upload in **⚙️ Setup** for personalised opinions.")
        profile = {"candidate_name": "Candidate", "skills": [], "years_of_experience_hint": "graduate"}
    with st.form("debate_form"):
        c1, c2    = st.columns(2)
        job_title = c1.text_input("Job Title", placeholder="e.g. Supply Chain Analyst")
        company   = c2.text_input("Company",   placeholder="e.g. DHL")
        c3, c4    = st.columns(2)
        location  = c3.text_input("Location", value="United Kingdom")
        salary    = c4.text_input("Salary",   placeholder="e.g. £35,000")
        spons_sel = st.selectbox(
            "Sponsorship status", ["unknown", "yes", "no"],
            format_func=lambda x: {
                "yes": "✅ Confirmed", "no": "❌ Explicitly no", "unknown": "❓ Not mentioned"
            }[x])
        job_desc = st.text_area("Job description excerpt (optional)", height=100)
        source   = st.text_input("Source", value="linkedin")
        run_btn  = st.form_submit_button("🧠 Run Agent Debate", type="primary", use_container_width=True)
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
            with st.spinner("🧠 Agents debating... (10–30s)"):
                try:
                    st.session_state["last_debate"] = run_debate_fn(job, profile)
                except Exception as exc:
                    st.error(f"Debate failed: {exc}")
                    st.session_state.pop("last_debate", None)
    result = st.session_state.get("last_debate")
    if not result:
        st.info("Fill in job details above and click **🧠 Run Agent Debate**.")
        return
    tier           = result.get("company_tier", "tier3")
    tier_colour, tier_label = TIER_STYLE.get(tier, ("#6b7280", "Unknown tier"))
    govuk          = result.get("govuk_verified")
    govuk_html     = (
        '<span style="color:#10b981;font-weight:700">✅ GOV.UK Verified Sponsor</span>' if govuk is True
        else '<span style="color:#ef4444;font-weight:700">❌ NOT on GOV.UK Register</span>' if govuk is False
        else '<span style="color:#f59e0b;font-weight:700">❓ register could not be checked</span>'
    )
    st.markdown(
        f'<div style="display:flex;gap:16px;align-items:center;padding:10px 16px;border-radius:8px;'
        f'background:{tier_colour}22;border:1px solid {tier_colour}55;margin-bottom:16px">'
        f'<span style="color:{tier_colour};font-weight:700">{tier_label}</span>'
        f' | {govuk_html}</div>', unsafe_allow_html=True)
    # Synthesis
    st.markdown("### 🎯 Final Verdict")
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
    st.markdown("### 🗣️ Agent Opinions")
    for ar in (result.get("agents") or []):
        agent_id   = ar.get("agent", "unknown")
        name       = ar.get("name", agent_id)
        opinion    = ar.get("opinion") or "*(no response)*"
        confidence = ar.get("confidence")
        colour, emoji, provider_label = AGENT_PROVIDER_COLOURS.get(agent_id, ("#6b7280", "⚪", agent_id))
        with st.container(border=True):
            ci, cb = st.columns([1, 9])
            ci.markdown(f'<div style="font-size:2rem;text-align:center;padding-top:8px">{emoji}</div>',
                        unsafe_allow_html=True)
            with cb:
                st.markdown(f'<span style="color:{colour};font-weight:700">{name}</span> '
                            f'<span style="color:#888;font-size:12px">— {provider_label}</span>',
                            unsafe_allow_html=True)
                st.markdown(opinion)
                st.markdown(_confidence_bar(confidence, "Confidence: "), unsafe_allow_html=True)
    # ATS / outreach / schedule
    ats = result.get("ats_bypass") or {}
    if ats:
        with st.expander("🤖 ATS Bypass Tip", expanded=True):
            st.error(f"❌ Don't say: `{ats.get('naive_answer', 'Yes')}`")
            st.success("✅ Say instead:")
            st.code(ats.get("smart_answer", ""), language=None)
            st.caption(ats.get("rationale", ""))
    outreach = result.get("linkedin_outreach") or ""
    if outreach:
        with st.expander("🔗 LinkedIn Outreach Message"):
            st.text_area("Edit before sending:", value=outreach, height=140, key="outreach_msg")
    with st.expander("🔬 Raw JSON"):
        st.json(result)


# ---------------------------------------------------------------------------
# Tab: Applications
# ---------------------------------------------------------------------------

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
        st.error(f"Could not load applications.\n\n**Detail:** `{err or 'empty response'}`\n\n"
                 "Restart the backend (■ Stop → ▶ Start in sidebar).")
        return
    apps  = data.get("applications", [])
    total = data.get("total_applications", len(apps))
    if not apps:
        st.info("📭 No applications yet. Run the AI Agent to start applying!")
        return
    counts = Counter((a.get("status") or "").lower() for a in apps)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", total)
    c2.metric("Draft", counts.get("draft", 0))
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
                st.caption(f"Updated: {app.get('updated_at', '—')}")
            with cc:
                opts       = ["draft", "ready", "submitted", "interview", "rejected"]
                cur_status = app.get("status", "draft")
                cur        = cur_status if cur_status in opts else "draft"
                ns         = st.selectbox("Status", opts, index=opts.index(cur),
                                          key=f"s_{app['application_id']}")
                notes      = st.text_input("Notes", value=app.get("notes") or "",
                                           key=f"n_{app['application_id']}")
                if st.button("Save", key=f"sv_{app['application_id']}"):
                    res, e2 = _patch(f"/applications/{app['application_id']}/status",
                                     {"status": ns, "notes": notes or None, "run_id": None})
                    if res:
                        st.success("Saved")
                        st.rerun()
                    else:
                        st.error(e2)


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
        log_txt = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        if log_txt.strip():
            with st.expander("📔 Backend startup log", expanded=True):
                st.code(log_txt[-3000:], language="")
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
            st.error(f"{marker} `{pkg}` NOT installed — `pip install {pkg}`")
    if status == "Running":
        data, _ = _get("/openapi.json")
        if data:
            st.write(f"**{len(data.get('paths', {}))} API routes active**")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

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
            st.success(msg) if ok else st.error(msg)
            st.rerun()
        if c2.button("■ Stop", use_container_width=True):
            ok, msg = stop_backend()
            st.success(msg) if ok else st.error(msg)
            st.rerun()
        st.markdown("---")
        st.session_state.candidate_email = st.text_input(
            "Your email", value=st.session_state.candidate_email,
            placeholder="your@email.com")
        p = st.session_state.get("resume_profile")
        if p:
            st.success(f"📎 {st.session_state.resume_filename}")
            name = _sidebar_name(p, st.session_state.resume_filename)
            st.caption(f"{name} | {len(p.get('skills') or [])} skills "
                       f"| {p.get('years_of_experience_hint') or '?'}")
        else:
            st.info("📎 Upload CV in ⚙️ Setup tab")
        if st.button("↻ Refresh", use_container_width=True):
            st.rerun()

    t1, t2, t3, t4, t5 = st.tabs(
        ["⚙️ Setup", "🤖 AI Agent", "🧠 Agent Debate", "📋 Applications", "🩺 Health"]
    )
    with t1: tab_setup()
    with t2: tab_agent()
    with t3: tab_debate()
    with t4: tab_applications()
    with t5: tab_health()


if __name__ == "__main__":
    main()
