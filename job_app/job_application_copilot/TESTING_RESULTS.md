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

---

## 9. Conda Detection Fix (non-standard install path with a space)

### The exact user-reported failure

The launcher printed **"[ERROR] Could not find Anaconda / Miniconda on this
machine"** even though conda was installed. In their Anaconda Prompt,
`conda info --base` returned:

```
C:\Users\gunja\anaconda3\New folder
```

i.e. the base is **one level deeper than normal** (a sub-folder literally named
`New folder`) **and contains a space**.

### Why the old detection missed it

The previous STEP 0 only tried:
1. `CONDA_EXE` (unset when you double-click a `.bat` from Explorer — that env var
   is only set inside an Anaconda Prompt),
2. `where conda` (fails — conda isn't on the plain-`cmd.exe` PATH, only on the
   Anaconda Prompt's PATH),
3. a **fixed list of exact paths** (`%USERPROFILE%\anaconda3`,
   `...\miniconda3`, `C:\ProgramData\Anaconda3`, …).

`C:\Users\gunja\anaconda3\New folder` is not in that fixed list (extra nested
folder, custom name), so every check fell through and the script gave a
misleading "install conda" message to a user who already had it.

### The new detection (a real search, not a fixed list)

STEP 0 was rewritten to resolve a `CONDA_BASE` via, in order:

0. **Manual override** — a `set "CONDA_BASE=..."` line near the top (and it
   honours a `CONDA_BASE` *user env var*), so a user can hard-code the exact path
   from `conda info --base` as a guaranteed escape hatch. Validated (must contain
   `Scripts\activate.bat`) before use.
1. **`CONDA_EXE`** → derive the base as its grandparent folder.
2. **`where conda`** → derive the base from conda's location.
3. **Real bounded search** — `:scan_root` walks each common root
   (`%USERPROFILE%`, `%LOCALAPPDATA%`, `%LOCALAPPDATA%\Continuum`, `%ProgramData%`)
   **and every sub-folder up to 2 levels deep**, using nested `for /d` loops
   (not a fixed name list). `:check_dir` accepts a folder that has
   `condabin\conda.bat` + `Scripts\activate.bat` (or `Scripts\activate.bat` +
   `python.exe`). Depth-2 from `%USERPROFILE%` reaches
   `…\anaconda3\New folder`. Well-known drive-root installs
   (`C:\anaconda3`, `C:\ProgramData\Anaconda3`, …) are checked shallowly to avoid
   a slow full `C:\` walk.
4. **Registry fallback** — `:scan_registry` reads
   `HK{CU,LM}\Software\Python\ContinuumAnalytics` (and `PythonCore`) and accepts
   the first `REG_SZ` whose data is a valid base (has `Scripts\activate.bat`).

**Quoting:** every path variable is used quoted (`"%VAR%"`, `"%%~fA"`,
`"!CONDA_ACT!"`) and activation is `call "%CONDA_BASE%\Scripts\activate.bat"
jobcopilot`, so the space in `New folder` does not break anything.

If all of that still fails, the error message no longer says "install conda".
It now tells the user to run `conda info --base`, then either paste the path into
the `CONDA_BASE=` line **or** `setx CONDA_BASE "<path>"` — with the user's exact
example path shown.

### Proof the search finds the space path (simulated tree)

A `.bat` can't run on Linux, so the `:scan_root`/`:check_dir` algorithm was
translated 1:1 to a shell script and run against a fake tree reproducing the
exact scenario:

```
fake_home/
  anaconda3/New folder/condabin/conda.bat      <- TARGET (depth 2, has a space)
  anaconda3/New folder/Scripts/activate.bat
  anaconda3/New folder/python.exe
  Documents/stuff/  Downloads/  Desktop/        <- decoys
  project/venv/Scripts/{activate.bat,python.exe} <- venv decoy (must NOT match)
```

Result:

```
=== Run search against USERPROFILE=fake_home ===
FOUND: /tmp/.../fake_home/anaconda3/New folder      <-- space + extra depth handled

=== Negative control: only the venv decoy ===
NOT FOUND  (exit=1)                                  <-- no false positive
```

The same algorithm and scenario are encoded as a regression test,
`tests/test_conda_detection.py` (4 tests): finds the space/`New folder` base at
non-standard depth, rejects a plain virtualenv, still finds the standard
`…\anaconda3` layout, and asserts `launch_app.bat` still contains the search +
registry + manual-override pieces. Full suite: **55 passed** (was 51).

### What still can't be guaranteed without a Windows machine

The traversal/match **logic** is proven, but real `cmd.exe` behavior on the
user's box can't be executed here — specifically `for /d` depth-2 timing on very
large profile trees, and `reg query` output formatting on their Windows build.
The **manual `CONDA_BASE` override remains the guaranteed fallback**: pasting the
exact `conda info --base` output bypasses all auto-detection, and the launcher
validates and uses it directly (spaces included).

---

## 10. Streamlit Launch Fix (STEP 4 of launch_app.bat)

### Symptom
On the user's machine the launcher now gets past conda detection (section 9),
starts the backend, and health-checks it successfully:

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     127.0.0.1:xxxxx - "GET /health HTTP/1.1" 200 OK
```

…but **Streamlit never starts** — no browser opens, no app appears.

### Root cause — one line: `--server.headless false`

STEP 4 launched Streamlit with:

```bat
python -m streamlit run app.py --server.port %UI_PORT% --server.headless false
```

On a **first run** (no saved Streamlit credentials), `--server.headless false`
makes Streamlit print an **interactive first-run prompt and then BLOCK on stdin**:

```
👋 Welcome to Streamlit!
If you'd like to receive helpful onboarding emails … please enter your email
address below. Otherwise, leave this field blank.
Email:
```

Streamlit waits at `Email:` for the user to type something and press Enter before
it finishes starting or opens a browser. From a double-clicked `.bat` this looks
exactly like "nothing happened": no browser, no app, no obvious output.

This was a **latent bug**: at commit `eb922b6` the user's conda base
(`…\anaconda3\New folder`) was never detected, so the launcher died at STEP 0 and
**never reached STEP 4**. The conda-detection fix (`1aa695a`) let the launcher
reach STEP 4 for the first time — exposing this pre-existing prompt-block.

The dependency warning (`RequestsDependencyWarning`) is **unrelated / cosmetic**
— proven below, Streamlit starts fine whether or not the warning is present.

### The fix (scoped entirely to STEP 4 — conda + backend/health-poll untouched)

1. `--server.headless true` — skips the interactive email prompt, so Streamlit
   starts immediately and non-interactively.
2. Streamlit runs in **its own titled window** via `start "JobCopilot UI …"
   cmd /k`, using the same resolved full python path (`"!PYTHON_EXE!"`) the
   backend already uses — so any startup error stays visible instead of vanishing.
3. Because headless mode does **not** auto-open a browser, the launcher **polls
   the UI port** (`http://127.0.0.1:%UI_PORT%/`) and then opens the browser
   itself: `start "" "http://localhost:%UI_PORT%"`. This guarantees a browser
   opens even if the OS default-browser association is broken — directly
   addressing the "no browser opens" symptom.
4. Clear error + `pause` if the UI does not come up within 60s.

### Proof (run in the sandbox, mirroring the fixed flow, fresh `$HOME` = first run)

Contrast run with the OLD flag first — `--server.headless false` blocks:

```
👋 Welcome to Streamlit!
… please enter your email address below. Otherwise, leave this field blank.
Email:                         <-- BLOCKS here; no banner, no browser
```

Fixed flow — backend health-poll success immediately followed by Streamlit up:

```
===== STEP 3: backend start + health poll =====
>> backend healthy after 4s (HTTP 200)
===== STEP 4: streamlit --server.headless true (fresh HOME, first run) =====
>> streamlit UP after 2s (HTTP 200) -> launcher opens browser here
===== streamlit banner =====
  You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501
email-prompt lines: 0
RequestsDependencyWarning lines: 0
===== final HTTP state =====
backend /health -> 200
streamlit /   -> 200
Streamlit                      <-- 8501 serves Streamlit HTML
```

With `--server.headless true` the "Email:" prompt is gone (0 lines) and the UI
serves HTTP 200 as a direct continuation of the backend health-poll success.

### RequestsDependencyWarning — separate cosmetic cleanup

`requests` validates its dependency stack at import and warns:

```
RequestsDependencyWarning: urllib3 (…) or chardet (…)/charset_normalizer (…)
doesn't match a supported version!
```

Cause: `chardet >= 6` is rejected by `requests`' import-time check. It is a
warning only — the backend and Streamlit both start fine with it present (proven
above; Streamlit came up with the warning still emitted before the pin). Pinned
in `requirements.txt` to bounded, compatible versions **for these three packages
only**:

```
urllib3<3
charset-normalizer<4
chardet<6
```

Verified in a **fresh venv**: with these bounds `import requests` is silent (no
warning), and nothing else breaks.

### Regression tests

`tests/test_streamlit_launch.py` (6 tests) guards the fix: STEP 4 uses
`--server.headless true` (and never `false`), invokes `"!PYTHON_EXE!"` for
Streamlit, opens the browser itself, polls the UI port, keeps the backend
health-poll intact, and confirms the `requirements.txt` pins. **Full suite: 61
passed** (was 55).

---

## 11. Health-Poll Hang Fix (STEP 3 + STEP 4 of launch_app.bat)

### Symptom (real Windows machine, two windows observed)
- **"JobCopilot Backend" window:** uvicorn started, `Application startup complete`,
  and crucially `127.0.0.1:xxxxx - "GET /health HTTP/1.1" 200 OK` — the backend
  genuinely **is** healthy and **did** answer the health check with 200.
- **Original launcher window:** stuck forever at
  `[3/4] Starting backend API ...` / `Waiting for the backend to become healthy...`.
  It never prints `Backend is healthy.`, never advances to `[4/4]`, and no
  "JobCopilot UI" window ever opens.

So the PowerShell poll got its 200 but control never came back to `cmd.exe` — a
hang **after** a successful response.

### Root-cause attempt with PowerShell Core (pwsh)
Installed PowerShell 7.4.6 (Linux x64 tarball) in the sandbox and ran the **exact**
`.bat` one-liner against a real running backend:

```
backend health via curl: 200
pwsh_rc=0 elapsed=0s
```

pwsh exits **promptly (0s, rc=0)** on a 200 — it does **not** reproduce the hang.
That is expected and informative: the user's machine uses the built-in **Windows
PowerShell 5.1** (`powershell.exe`, .NET Framework), not pwsh 7 (.NET Core). 5.1's
`Invoke-WebRequest` has well-known behaviours pwsh 7 dropped (IE-engine init,
system-proxy/WPAD probing, progress-stream rendering, connection disposal on exit)
that can leave `powershell.exe` failing to return control even after the server
logged a 200. **Conclusion: the exact 5.1 hang could not be reproduced from Linux —
which is precisely why the fix removes PowerShell from the hot path entirely.**

### The fix — curl.exe retry loop (PowerShell only as fallback)
Both polls now `call :poll_url "<url>" <max_seconds>`, a shared subroutine that:
1. Prefers **`curl.exe`** (built into Windows 10 1803+ and all Windows 11, at
   `%SystemRoot%\System32\curl.exe`; also honours it on PATH).
2. Runs a plain batch retry loop:
   `curl.exe -s -o nul -w "%{http_code}" --connect-timeout 2 --max-time 5 <url>`,
   sets `POLL_OK=1` on `200`, else `timeout /t 1` and retries.
3. Falls back to the original PowerShell one-liner **only** if `curl.exe` is truly
   absent (very old Windows), so nothing regresses on edge-case boxes.

`curl.exe` has no interpreter startup cost, no module autoload, no
execution-policy/quoting edge cases, and hard `--connect-timeout`/`--max-time`
bounds — it cannot hang after a 200.

Conda detection (STEP 0), dependency check (STEP 1) and port-clearing (STEP 2) are
**untouched**.

### Proof 1 — retry-loop logic (1:1 bash/curl translation of :poll_url)

```
(a) already-up server: POLL_OK='1' elapsed=0s          -> PASS
(b) never-up server:   POLL_OK='<empty>' elapsed=3s    -> PASS (clean timeout, no hang)
(c) slow-start (5s):   POLL_OK='1' elapsed=6s          -> PASS (waited then succeeded)
(d) no-hang guarantee: script bounded, reached end     -> ALL DONE
```

### Proof 2 — full launcher flow end-to-end (new poll logic)

```
[0/4] (conda activate == venv)
[1/4] Dependencies OK.
[3/4] Starting backend API on http://127.0.0.1:8000 ...
      Waiting for the backend to become healthy...
      Backend is healthy.
[4/4] Starting the Streamlit UI on http://localhost:8501 ...
      Waiting for the UI to become available...
      UI is up. Opening your browser at http://localhost:8501 ...
============================================================
 Both servers are now running, each in its own window:
   * Backend API : http://127.0.0.1:8000
   * Streamlit UI: http://localhost:8501
============================================================
backend /health -> 200
streamlit /   -> 200
```

The launcher now advances past the health poll and reaches **"Both servers are now
running"** — the exact step that previously hung.

### Regression tests
`tests/test_health_poll.py` (6 tests): a Python mirror of `:poll_url` (same curl
flags) proves prompt-200, clean timeout on a dead port, and slow-start wait; plus
static guards that `launch_app.bat` uses the curl-based `:poll_url`, keeps exactly
one PowerShell invocation (the fallback, after the label), and gates both call
sites on `POLL_OK`. **Full suite: 67 passed** (was 61), zero regressions.

---

## 12. Launcher Rewritten in Python (`launch.py`)

### Why — batch was the wrong foundation, three rounds running

The orchestration logic in `launch_app.bat` failed in a new, batch-specific way
every round, each time with **no error surfaced to the user**:

1. **PowerShell hang** — the `powershell Invoke-WebRequest` health poll received a
   200 but never returned control to `cmd.exe`; the launcher hung forever at
   "Waiting for the backend to become healthy...".
2. **Streamlit headless block** — `--server.headless false` made a first-run
   Streamlit print an interactive email prompt and block on stdin; nothing
   appeared to happen.
3. **Silent window-vanish** — the curl.exe batch retry loop caused the entire
   launcher window to *disappear* before a single `GET /health` was even logged
   (the "JobCopilot Backend" window showed uvicorn up + "Application startup
   complete" but **no** `GET /health` line at all). A batch control-flow/quoting
   failure terminated `cmd.exe` itself, leaving no traceback.

Windows batch is simply unreliable for subprocess orchestration, polling with
timeouts, and robust error surfacing. Python has vastly better primitives, and —
the decisive point — **any failure prints a real traceback instead of a window
silently closing.** So all of STEP 1–4 moved into `launch.py`.

### What `launch.py` does

- **Top-level `try/except`** around the whole body: on any uncaught error it
  prints the full traceback and calls `input("Press Enter to exit...")`, so the
  console can **never** silently vanish again, no matter what fails.
- **Dependencies** — import-check `streamlit`/`fastapi`/`uvicorn`; if missing, run
  `pip install -r requirements.txt` with clear status/errors.
- **Port clearing** — parse `netstat -aon` (Windows) / `lsof` (POSIX) to find and
  `taskkill`/`kill` anything already listening on 8000/8501.
- **Backend** — `Popen([sys.executable, -m uvicorn backend.main:app ...])`, output
  streaming to the console, then poll `http://127.0.0.1:8000/health` with
  `urllib.request` (stdlib only — no curl, no PowerShell). Every iteration also
  checks `proc.poll()`, so a backend that crashes on startup is reported in ~1s
  with its return code instead of waiting the full 30s.
- **Streamlit** — same pattern (`--server.headless true`), poll
  `http://127.0.0.1:8501/`, then `webbrowser.open(...)`.
- **Shutdown** — both subprocesses registered with `atexit`; closing the console
  (or pressing Enter) terminates them.

`launch_app.bat` is now minimal: it keeps ONLY the proven STEP 0 conda
detection/activation (untouched — confirmed working on the user's real machine,
including the `C:\Users\gunja\anaconda3\New folder` path) and then
`call "!PYTHON_EXE!" launch.py` followed by an unconditional `pause`, so the
window always stays open to show Python's output including any traceback. The old
`:poll_url` subroutine (and all curl.exe/PowerShell polling) was removed.

### Proof 1 — end-to-end, Python polling only

Ran the real `launch.py` functions against a live backend + Streamlit in the
sandbox (no curl/PowerShell/batch anywhere in the hot path):

```
[1/4] Checking dependencies...
      Dependencies OK.
[2/4] Clearing old processes on ports 8000 and 8501 (if any)...
      Done.
[3/4] Starting backend API on http://127.0.0.1:8000 ...
      Waiting for the backend to become healthy...
      Backend is healthy.
[4/4] Starting the Streamlit UI on http://localhost:8501 ...
      Waiting for the UI to become available...
============================================================
 Both servers are now running (proof driver):
   * Backend API : http://127.0.0.1:8000/health
   * Streamlit UI: http://127.0.0.1:8501/
============================================================
independent check backend /health -> 200
independent check streamlit /     -> 200
RESULT: END-TO-END PASS
```

Reaches **"Both servers are now running"** — the step that previously hung/vanished.

### Proof 2 — crash detection is fast

Pointed the backend at a non-existent app (`backend.main:NOPE_does_not_exist`) so
uvicorn exits immediately, then ran the real `wait_until_healthy`:

```
ok=False reason='process exited (code 1)' elapsed=3.0s
RESULT: CRASH-DETECTION PASS (fast failure, not full 30s timeout)
```

The immediate crash is detected via `proc.poll()` in **3.0 s** (return code
surfaced), not after the full 30 s budget.

### Regression tests

- New `tests/test_launch_py.py` (11 tests): `wait_until_healthy` detects a prompt
  200, waits for a slow-starting server, times out cleanly on a dead port, detects
  an immediately-crashing subprocess fast (return code in the reason), and reports
  healthy when the process stays alive; `http_status` returns `None` on a refused
  connection; plus static guards that `launch_app.bat` hands off to `launch.py`,
  no longer contains any `:poll_url`/`curl.exe`/PowerShell polling, keeps the STEP
  0 conda subroutines, and always `pause`s — and that `launch.py` wraps its body
  and pauses on error.
- `tests/test_streamlit_launch.py` updated to assert the STEP 4 behaviours
  (headless true, resolved `sys.executable`, browser-open, UI poll, backend health
  poll) against their new home in `launch.py`.
- Obsolete `tests/test_health_poll.py` (which guarded the removed batch curl
  `:poll_url`) deleted; its Python-side equivalents now live in `test_launch_py.py`.
- Requirements pins for the `RequestsDependencyWarning` fix confirmed still present
  and correct: `urllib3<3`, `charset-normalizer<4`, `chardet<6`.

**Full suite: 72 passed** (67 prior − 6 removed + 11 new), zero regressions.

---

## 13. F-string Syntax Fix — profile page crashed on Python < 3.12

### The bug

The launcher now opens the browser, but the Setup page crashed at render time with
a real Python error surfaced in the browser:

```
File ".../app.py", line 556
    st.write(f"👤 **Name:** {p.get('candidate_name') or '—'}")
SyntaxError: f-string expression part cannot include a backslash
```

### Why it only breaks on certain Python versions

The em-dash placeholder was written as an escaped character (`'—'`) placed
**directly inside an f-string `{expression}` part**. PEP 701 relaxed the f-string
grammar in **Python 3.12** to allow backslashes inside `{...}`, but on **Python
3.9–3.11 this is a hard `SyntaxError`**. The project docs ask for
`conda create -n jobcopilot python=3.12`, but the user's actual `jobcopilot`
environment was older, so the module imported far enough to boot and then the
page crashed the moment it tried to compile this line. Expected/documented Python
is **3.12** (README.md, SETUP.md, launch_app.bat, TESTING_RESULTS.md all pin it),
but the fix is written to be compatible with **Python 3.9+** regardless of the
user's env.

### The fix

Escaped characters used inside f-string braces were moved into plain module-level
string constants near the top of `app.py` (line 103-105):

```python
EM_DASH    = "—"                # em-dash placeholder for a missing value
ICON_WARN  = "⚠️"        # warning sign
ICON_CHECK = "✅"                # check mark
```

The f-strings then reference the constant instead of an inline escape, which parses
on every supported Python version.

### All locations fixed (`app.py`)

| Line | Fixed expression |
|------|------------------|
| 564  | `f"...**Name:** {p.get('candidate_name') or EM_DASH}"` |
| 565  | `f"...**Email:** {p.get('email') or EM_DASH}"` |
| 566  | `f"...**Experience:** {p.get('years_of_experience_hint') or EM_DASH}"` |
| 571  | `f"...**Skills ({len(skills_list)}):** {', '.join(skills_list) or EM_DASH}"` |
| 812  | `f"{ICON_WARN if review_mode else ICON_CHECK} {fit}% | {title} @ {co} | {src}"` |
| 1061 | `f"Updated: {app.get('updated_at', EM_DASH)}"` |

A full-tree AST scan of every `.py` under the project confirmed **6 offenders
before, 0 after** — all were in `app.py`.

### Proof — the page renders, not just parses

Booted the Setup page through Streamlit's `AppTest` (which actually executes the
f-string line) on both the populated and the missing-value fallback paths:

```
[full] rendered OK; no exception; 'Name:' line present
   -> 👤 **Name:** Ada Lovelace
[missing-values] rendered OK; no exception; 'Name:' line present
   -> 👤 **Name:** —
RESULT: PROFILE-RENDER PASS
```

### CI-style guards so this can't silently ship again

- `tests/test_syntax_compat.py`:
  - `test_no_backslash_inside_fstring_expressions` — the **authoritative** check.
    Walks the AST of every `.py`, recovers the source text of each f-string
    `{expression}` via `ast.get_source_segment`, and fails on any backslash. This
    catches the regression on **any** host, including Python 3.12+ where the code
    parses fine and a plain parse would not notice.
  - `test_parses_under_min_supported_python` — parametrized over every `.py`,
    `ast.parse(..., feature_version=(3, 9))`. Catches ordinary syntax errors and
    adds real f-string coverage on <3.12 CI. (Note: `feature_version` does not
    re-impose the pre-3.12 f-string tokenizer rule on a 3.12+ host, which is
    exactly why the dedicated AST scan above exists.)
- `tests/test_profile_render.py` — two `AppTest` tests that render the actual
  extracted-profile block and assert no exception on both the full and EM_DASH
  fallback paths.

**Full suite: 184 passed**, zero regressions.
