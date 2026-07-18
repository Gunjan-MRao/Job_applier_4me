# Testing Results — Job Application Copilot

This document records what was broken, what was fixed, exactly how the pipeline
was tested, the concrete output it now produces, and the real-world environment
variables you must supply to unlock the paid/optional features.

The headline: **the pipeline now runs end-to-end and produces a scored, matched
job with a drafted cover letter and cold email — with zero API keys configured.**

---

## 1. What was broken

| # | File | Bug | Impact |
|---|------|-----|--------|
| 1 | `backend/core/config.py` | `.env` was loaded from `parents[3]` (`job_app/`) instead of `parents[2]` (`job_application_copilot/`), so the real `.env` next to the app was never read. Many settings (`groq_api_key`, email, storage dirs, Adzuna, etc.) were also missing entirely. | Keys placed in the documented location were silently ignored; `/resume/parse` crashed with 500 because `settings.resume_dir` did not exist. |
| 2 | `backend/services/automation_runtime.py` | Groq (the intended FREE primary LLM) was never wired into the provider chain. | AI drafts never used Groq even with a valid key. |
| 3 | `backend/services/automation_runtime.py` | `jobs_scanned` was recorded **before** the built-in fallback jobs were injected, so a keyless run reported `0 jobs found`. | UI showed "0 jobs" even when jobs were matched and drafted. |
| 4 | `backend/services/lead_finder.py` | `_guess_domain` didn't strip company stopwords (Ltd, UK, Services…) or special chars, producing wrong recruiter domains. | Cold-outreach domain guesses were wrong (e.g. `smith.com` instead of `smithjones.com`). |
| 5 | `app.py` | LLM key-status block had broken/convoluted logic and didn't read the `.env` file. | Sidebar mis-reported whether an LLM key was configured. |
| 6 | `tests/test_api.py` | Tests hit stale endpoints (`/api/v1/runs`) that returned 404. | Test suite failed out of the box. |

## 2. What was fixed

- **`config.py`** — rewrote path resolution to `_PROJECT_ROOT = parents[2]`; added
  every missing setting: `database_url`, `groq_api_key`, `gemini/hf/openai/anthropic`
  keys, `adzuna_app_id/key`, `hunter/apollo`, email (`email_address`/`email_password`
  with `SMTP_USER`/`SMTP_PASS` aliases), `smtp_host/port`, and all storage dirs.
- **`automation_runtime.py`** — added `_groq()` (model `llama-3.3-70b-versatile`) and
  prepended it to the `_llm()` provider chain (Groq → Gemini → HuggingFace → OpenAI →
  Anthropic → offline templates). Fixed `jobs_scanned` to be recorded after fallback
  jobs are injected.
- **`lead_finder.py`** — added `_DOMAIN_STOPWORDS` and rewrote `_guess_domain` to drop
  stopwords, strip non-alphanumerics, and join words.
- **`app.py`** — added an `_env_key()` helper that reads both the environment and the
  `.env` file; simplified the LLM key/provider status logic.
- **`.env.example`** — rewrote to document every variable with exact names and free
  sign-up links.

## 3. How it was tested

Run from `job_app/job_application_copilot/`:

```bash
python -m pytest -q          # 50 passed
```

The end-to-end test (`tests/test_pipeline_e2e.py`) stubs **only** the two network
scrapers (`scrape_all_jobspy`, `scrape_all_html`) so the run is offline and
deterministic. Everything else — resume parsing, scoring/matching, and offline
draft generation — runs the **real** code paths. It asserts the run completes with
`jobs_scanned > 0`, `jobs_matched > 0`, at least one applied job, and that the top
match carries a personalised cover letter (candidate name + company) and a cold
email with a `Subject:` line.

Tests:
- `test_resume_parser_extracts_real_fields` — real parser pulls email, skills
  (supply chain, sap), and a years-of-experience hint from the sample resume.
- `test_pipeline_produces_drafted_application` — full offline pipeline yields a
  drafted application.
- `test_offline_generation_is_used_without_keys` — with all LLM providers forced to
  `None`, offline templates fill the gap.

## 4. Concrete sample output (offline, no keys)

Parsed profile: **Bindu Sharma** — `bindu.sharma@example.com`, 3+ years, 17 skills
(supply chain, logistics, procurement, SAP, Excel, Power BI, SQL, …).

Top match: **Supply Chain Analyst @ DHL**.

**Cover letter (offline template):**
```
Dear Hiring Team at DHL,

The Supply Chain Analyst role at DHL is exactly the kind of position I have
been working towards.

My background in Supply Chain Analyst has given me 3+ years of hands-on
experience with supply chain, logistics, procurement. I have hands-on
experience with SAP which I understand is central to this role.

I am ready to contribute from day one and would welcome the chance to discuss
how I can add value — would you be open to a brief call this week?

One practical note: I would require a Certificate of Sponsorship under the
Skilled Worker route...
```

**Cold email (offline template):**
```
Subject: Supply Chain Analyst — Bindu Sharma

Hi,

I came across the Supply Chain Analyst role at DHL and wanted to reach out
directly.

I have 3+ years experience in supply chain, logistics, procurement and am
actively looking for a supply chain or logistics role in the UK...
```

## 5. Environment variables you must supply

The app runs 100% free with **no keys**. Add keys to unlock AI drafts and real
email sending. Put them in a `.env` file inside `job_app/job_application_copilot/`
(copy from `.env.example`).

**To get AI-written drafts (recommended, free):**
- `GROQ_API_KEY` — free at https://console.groq.com (no credit card). Primary LLM.

**To actually send cold emails (free with Gmail):**
- `EMAIL_ADDRESS` — your sending address (e.g. Gmail).
- `EMAIL_PASSWORD` — a Gmail **App Password** (not your login password); create at
  https://myaccount.google.com/apppasswords after enabling 2-Step Verification.
  (`SMTP_USER` / `SMTP_PASS` are accepted as aliases.)
- `SMTP_HOST` — defaults to `smtp.gmail.com`.
- `SMTP_PORT` — defaults to `465`.

**Optional — extra LLM fallbacks (only used if `GROQ_API_KEY` is unset):**
- `GEMINI_API_KEY` (free), `HF_API_KEY` (free), `OPENAI_API_KEY` (paid),
  `ANTHROPIC_API_KEY` (paid).

**Optional — better job coverage / recruiter email discovery:**
- `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` (free tier) — https://developer.adzuna.com/
- `HUNTER_API_KEY`, `APOLLO_API_KEY` — recruiter-email finders.

No credentials are committed to the repo. `.env` is gitignored; only `.env.example`
(with blank values) is tracked.

---

## 6. Live App Boot Test (both servers actually started)

Unlike section 3 (which exercised the pipeline via pytest), this section records
**both real servers being started and driven over HTTP** the way a user would,
with a **blank `.env`** (copied from `.env.example`, zero API keys).

### Bug found and fixed during the live boot test

`GET /jobs` returned **500 `sqlite3.OperationalError: no such table: jobs`**. Root
cause: `init_db()` (which runs `Base.metadata.create_all`) existed in
`backend/db/engine.py` but was **never called** — nothing created the SQLite schema
at startup. Fixed by calling `init_db()` in the FastAPI `startup` event in
`backend/main.py`. After the fix, deleting `storage/jobs.db` and restarting recreates
the `jobs` and `runs` tables automatically, and `/jobs` returns 200.

### Start commands

```bash
cd job_app/job_application_copilot
cp .env.example .env                      # blank keys — zero-cost setup

# Backend
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Streamlit UI (separate process)
python -m streamlit run app.py --server.headless true \
       --server.port 8501 --server.address 127.0.0.1
```

### Backend startup log (clean)

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```
Tables verified after boot: `['jobs', 'runs']`.

### Streamlit startup log (clean)

```
  You can now view your Streamlit app in your browser.
  URL: http://127.0.0.1:8501
```

### Endpoint checks (curl, blank .env)

```
GET  /health                         -> 200  {"status":"ok","service":"job_application_copilot"}
GET  /                               -> 200
POST /resume/parse (sample docx)     -> 200  name=Bindu Sharma, email=bindu.sharma@example.com, skills=17, yoe=3+ years
POST /automation/start               -> 200  {"run_id":"...","status":"running"}
GET  /automation/status/{run_id}     -> 200  status=completed (polled to completion)
GET  /automation/runs                -> 200  {"runs":[...]}
GET  /jobs                           -> 200  {"jobs":[],"total":0}   (was 500 before the init_db fix)
GET  /applications/{email}           -> 200  {candidate_email,total_applications,applications}
GET  http://127.0.0.1:8501/          -> 200  <title>Streamlit</title>
GET  http://127.0.0.1:8501/_stcore/health -> 200
```

Note: `/resume/parse` accepts `.pdf`/`.docx` only, so the `.txt` fixture was converted
to `sample_resume.docx` for the upload test. `/jobs` returns an empty list because the
live automation path keeps run state in memory (the `RUNS` dict), not the DB — the
important thing is it no longer 500s.

### Full end-to-end run over HTTP (blank .env)

Driving `/automation/start` → poll `/automation/status` to completion produced a real
result using live job scraping + real scoring + offline draft templates (no LLM key):

```
status: completed | stage: ✅ Done! | progress: 100
jobs_scanned: 205 | jobs_matched: 195 | jobs_applied: 195 | jobs_failed: 0
applied_jobs with cover_letter + cold_email: 195 / 195
TOP MATCH: Logistics Coordinator and Data Analyst @ Moët Hennessy (fit_score 55)
```

Top-match cover letter (offline template, personalised):
```
Dear Hiring Team at Moët Hennessy,

The Logistics Coordinator and Data Analyst role at Moët Hennessy is exactly the
kind of position I have been working towards.

My background in Supply Chain Analyst has given me 3+ years of hands-on experience
with supply chain, logistics, procurement. I have hands-on experience with SAP
which I understand is central to this role...
```

Top-match cold email (offline template):
```
Subject: Logistics Coordinator and Data Analyst — Bindu Sharma

Hi,

I came across the Logistics Coordinator and Data Analyst role at Moët Hennessy and
wanted to reach out directly.

I have 3+ years experience in supply chain...
```

### Process stability

Both processes stayed alive for the entire test (a full ~2-minute scrape + draft run
plus all endpoint calls) with **zero tracebacks / 500s in the backend log** after the
`init_db` fix. Both were then stopped cleanly. `pytest` still passes **50/50** after
the `main.py` change.

Bottom line: with no API keys at all, both servers boot cleanly and the app produces
195 matched jobs each with a drafted, personalised cover letter and cold email.

---

## 7. UI Button Flow Test (Playwright, real rendered Streamlit UI)

This section covers a **new bug report** made after using the actual Streamlit UI
(not just API calls): *as soon as you click "Parse resume", the app jumps straight
to the "Start AI Agent" step*, skipping the intended flow of **parse resume →
review the parsed profile → then explicitly go to the AI Agent**.

### The bug and its exact root cause

The root cause was **not** a session_state collision, an `if/elif` fallthrough, a
duplicate `key=`, or a stale rerun condition. It was a single deliberate line of
code in the "Parse resume" button handler in `app.py` (`tab_setup()`):

```python
# BEFORE (the bug):
st.session_state["resume_profile"]  = profile
st.session_state["resume_filename"] = fname
...
# Jump straight to AI Agent tab
_go(PAGE_AGENT)          # <-- navigates away on parse, skipping the review
```

`_go()` sets `st.session_state["page"]` and calls `st.rerun()`, so parsing the
resume immediately changed the page to the AI Agent view. The "📌 Extracted
profile" review block further down in `tab_setup()` was therefore never shown —
the user never got a chance to review the parsed data before the agent step.

### The fix (root cause, not a band-aid)

`_go(PAGE_AGENT)` was removed from the parse handler and replaced with a plain
`st.rerun()`, so the app stays on the Setup page and renders the parsed-profile
review. Advancing to the AI Agent step is now **only** the explicit
"🤖 Go to AI Agent ➤" button that already existed below the review.

```python
# AFTER (the fix):
st.session_state["resume_profile"]  = profile
st.session_state["resume_filename"] = fname
...
# Stay on Setup so the user can REVIEW the parsed profile below.
# Advancing to the AI Agent step is an explicit user action via the
# "Go to AI Agent" button — never an automatic jump on parse.
st.rerun()
```

A success banner was also added above the review:
`✅ Resume parsed — review the details below, then click Go to AI Agent when ready.`

### Playwright regression test

`tests/test_ui_button_flow.py` drives the **real rendered Streamlit UI** with a
headless Chromium browser. It is self-contained: it boots the FastAPI backend
(port 8010) and Streamlit (port 8511) with a blank `.env`, then:

1. loads the app and waits for the Setup page ("Upload your resume"),
2. uploads `tests/fixtures/sample_resume.docx`,
3. clicks **Parse resume**,
4. asserts the **"Extracted profile" review is visible**,
5. asserts **"Start AI Agent" is NOT present** (the skip bug would fail here),
6. clicks **"Go to AI Agent"** and asserts the **"AI Job Agent"** step appears.

The test **skips gracefully** (never fails the suite) if Playwright, the Chromium
browser, or the servers/ports are unavailable — so the offline suite stays green
in environments without a browser.

Playwright run output (with the fix in place):

```
PASS: 'Extracted profile' review is visible after Parse resume
PASS: 'Start AI Agent' is NOT shown after Parse resume (no skip)
PASS: 'AI Job Agent' step appears after clicking 'Go to AI Agent'
ALL SMOKE CHECKS PASSED

$ pytest tests/test_ui_button_flow.py -v
tests/test_ui_button_flow.py::test_parse_does_not_skip_to_agent PASSED   [100%]
1 passed in 5.96s
```

Full suite after adding the test: **51 passed** (was 50 + this new UI test).

### Backend "did not start" — findings and hardening

The report also said the backend "did not start" for the user (on Windows). The
backend is launched from **inside** the Streamlit UI via `start_backend()` in
`app.py` (not by `launch_app.bat`, which only starts Streamlit). Review findings:

- `launch_app.bat` uses robust Python discovery (py launcher, PATH, AppData,
  Program Files, Anaconda) and has **no** hardcoded Unix or `C:\` paths.
- `app.py` already uses `pathlib` for `BASE_DIR`, `PID_FILE`, `LOG_FILE`; a grep
  for hardcoded `/` and `C:\` paths found only a harmless careers URL, so there
  was no Windows path bug to fix.
- The real weakness was **silent failure**: if a dependency was missing or the
  child process exited immediately (e.g. port already in use), `start_backend()`
  gave no actionable message.

Hardening applied to `start_backend()` (and a new `_preflight_backend_deps()`):

- **Preflight check** before spawning: verifies `uvicorn`/`fastapi` are importable
  in the *exact* Python being used and that `backend/main.py` exists — returning a
  precise message with the interpreter path and the exact `pip install` command.
- **Immediate-exit detection**: the wait loop now checks `proc.poll()`; if the
  child dies, it reads the log tail and surfaces targeted hints —
  *"Address already in use" / "10048"* → port-conflict hint;
  *"ModuleNotFoundError" / "ImportError"* → pip-install hint.
- A clearer timeout message and a `finally` block that closes the log file handle.

**Honest limitation:** this was verified on Linux, so Windows-specific behavior
could not be fully reproduced in the sandbox. Without the user's **actual Windows
error log / console output**, the precise cause of their "backend did not start"
cannot be confirmed — but startup failures now print clear, actionable messages
(missing package + exact install command, port conflict, or a log tail on
immediate exit) instead of failing silently, which will make the real cause
visible the next time it happens on their machine.

---

## 8. `launch_app.bat` Verification (one-double-click launch)

Goal: double-clicking `job_app/job_application_copilot/launch_app.bat` on the
user's Windows machine (Anaconda, env named `jobcopilot`) should bring up the
**whole app** — backend + Streamlit UI + browser — with clear on-screen errors
and no window that flashes and closes.

### What was wrong with the original `.bat`

The original launcher had three real gaps for this user's setup:

1. **It never activated the `jobcopilot` conda environment.** It searched for
   *any* Python (py launcher, PATH, AppData, Program Files, even Anaconda's base
   `python.exe`) and ran that. On an Anaconda machine this typically lands on
   **base**, not `jobcopilot`, so the app ran against the wrong environment /
   wrong installed packages. (The README even said `conda activate jobhunter` —
   a different, non-existent name.)
2. **It never started the backend.** It only launched Streamlit and relied on the
   UI's in-app "Start" to spawn uvicorn. There was no `/health` wait, so nothing
   guaranteed the API was up.
3. **Browser timing / double-open.** It ran `start http://localhost:8501`
   *immediately* (before Streamlit was ready) **and** used `--server.headless
   false` (which also opens a browser) — a premature/blank tab plus a duplicate.

There were no hardcoded absolute paths in the `.bat` itself (it already used
`cd /d "%~dp0"`), so anchoring was fine.

### What was changed

`launch_app.bat` was rewritten to do all six required things:

- **(a) Activate `jobcopilot`.** Finds conda via `CONDA_EXE`, then `where conda`,
  then a list of standard Anaconda/Miniconda install locations; activates with the
  script-safe `call "<base>\Scripts\activate.bat" jobcopilot` form and verifies
  `CONDA_DEFAULT_ENV==jobcopilot`. If conda isn't found, or the env is missing, it
  prints the exact fix (`conda init cmd.exe`, or
  `conda create -n jobcopilot python=3.12 -y`) and `pause`s.
- **(b) `%~dp0` anchoring** so it works no matter where it's double-clicked from.
- **(c) Dependency check** — imports `streamlit, fastapi, uvicorn`; only runs
  `pip install -r requirements.txt` if something is missing, then re-checks, with
  a clear message + `pause` on failure.
- **(d) Backend start + real health wait** — launches uvicorn in its own titled
  window via `cmd /k` (so a traceback stays visible), then **polls
  `http://127.0.0.1:8000/health` for up to 30s** with PowerShell
  (`Invoke-WebRequest`, always present on Windows) before proceeding — no blind
  `timeout /t 5`.
- **(e) Streamlit + browser** — starts Streamlit with `--server.headless false`
  so Streamlit opens the default browser itself once ready (removed the premature
  manual `start`, fixing the double/blank-tab issue).
- **(f) Window stays open on failure** — every error path ends with `pause`, and
  the backend runs under `cmd /k`.

Also added `launch_app.sh` — the same sequence for macOS/Linux/Git-Bash and as a
fallback — and updated `README.md` / `SETUP.md` with the one-time `jobcopilot`
setup and the double-click flow.

### Proof the sequence actually runs (equivalent-shell proof in sandbox)

A `.bat` can't be executed in the Linux sandbox, so the identical command
*sequence* was proven by running `launch_app.sh` (a faithful mirror). The conda
step gracefully fell back to the sandbox's Python (no conda present), which
exercised steps 1–4 for real:

```
[0/4] Activating conda environment 'jobcopilot'...
      conda not found -- using 'python' on PATH.
      Python: /tmp/venv/bin/python
[1/4] Checking dependencies...
      Dependencies OK.
[2/4] Clearing old processes on ports 8000 and 8501 (if any)...
[3/4] Starting backend API on http://127.0.0.1:8000 ...
      Waiting for the backend to become healthy...
      Backend is healthy (PID 14841).
[4/4] Starting the Streamlit UI on http://localhost:8501 ...
      You can now view your Streamlit app in your browser.
      Local URL: http://localhost:8501

# independent endpoint checks while it ran:
backend   /health           -> 200
streamlit /_stcore/health   -> 200
```

**Failure path also proven** (health poll must fail fast, not hang 30s): pointing
uvicorn at a non-existent module made the backend exit immediately; the poll
detected the dead process and returned in **~1s** with `healthy=False`,
`exit_code=1`, and logged `Error loading ASGI app. Could not import module
"backend.nonexistent"`.

### What cannot be 100% guaranteed without a Windows machine

- The exact `conda`/`activate.bat` behavior on the user's specific Anaconda
  install (quoting of paths with spaces, `conda init` state, base-vs-env quirks)
  can't be executed here — only the logic was verified by careful read-through and
  by proving the equivalent POSIX sequence.
- The `.bat`'s health poll waits the full 30s before erroring (it can't easily
  watch the backend PID that runs in a separate `start` window), whereas the
  `.sh` breaks early on process death. In practice the `cmd /k` backend window
  shows the traceback instantly, so the user still sees the cause immediately.

**Fallbacks provided** if a Windows-only conda edge case still bites:
`launch_app.sh` (Git-Bash), and the documented manual two-terminal commands
(`uvicorn backend.main:app --reload` + `streamlit run app.py`) in `README.md` /
`SETUP.md`.
