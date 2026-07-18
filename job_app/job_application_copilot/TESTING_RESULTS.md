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
