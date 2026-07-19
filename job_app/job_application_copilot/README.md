# job_application_copilot

Generic AI-assisted job search and application platform.

## Goals
- Upload any resume/CV.
- Extract candidate profile automatically.
- Ask the user what they want.
- Search relevant jobs.
- Score role fit.
- Generate tailored application materials.
- Review output before submission.
- Automate supported job applications.

## Project structure

```text
job_application_copilot/
  backend/
    api/
    core/
    db/
    models/
    schemas/
    services/
      parser/
      profile/
      search/
      match/
      generate/
      review/
      apply/
    workers/
    main.py
  frontend/
  storage/
    resumes/
    generated/
    screenshots/
    logs/
  tests/
```

## Quick start (Windows — one double-click)

**One-time setup** (open the *Anaconda Prompt* and run these once):

```bat
conda create -n jobcopilot python=3.12 -y
conda activate jobcopilot
cd job_app\job_application_copilot
pip install -r requirements.txt
copy .env.example .env
```

**Every time after that:** just double-click **`launch_app.bat`** in
`job_app\job_application_copilot\`. It will:

1. activate the `jobcopilot` conda environment,
2. verify/install dependencies,
3. start the backend API and wait until it is healthy,
4. start the Streamlit UI and open your browser at http://localhost:8501.

If anything goes wrong the launcher prints a clear error and keeps the window
open (it will not flash and vanish). A separate "JobCopilot Backend" window shows
the API log; a copy is also saved to `backend_startup.log`.

> The environment **must** be named `jobcopilot`. If it is missing, the launcher
> tells you the exact `conda create` command to fix it.

### macOS / Linux / Git-Bash

Use the equivalent shell launcher (same steps):

```bash
cd job_app/job_application_copilot
./launch_app.sh
```

### Manual run (fallback)

```bash
conda activate jobcopilot
cd job_app/job_application_copilot
pip install -r requirements.txt
copy .env.example .env             # cp on macOS/Linux
uvicorn backend.main:app --reload  # backend -> http://127.0.0.1:8000
streamlit run app.py               # UI      -> http://localhost:8501
```

Useful URLs:
- UI: http://localhost:8501
- API root: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/health
- Docs: http://127.0.0.1:8000/docs

## Core pipeline architecture (rebuilt)

The job-search core lives in a small, self-contained, unit-tested package:
`backend/pipeline/`.

```text
resume profile + preferences
    -> gather_jobs()      Adzuna (primary) -> Reed (secondary)
                          -> legacy scraper (opt-in) -> mock (last resort)
    -> score_job()        deterministic 0-100 fit score + sponsorship class
    -> draft_cover_letter / draft_cold_email   (Groq LLM, offline fallback)
    -> ranked, drafted results
```

| Module | Responsibility |
| --- | --- |
| `pipeline/job_sources.py` | Fetch jobs in one canonical shape. Adzuna JSON API is primary, Reed is secondary, the legacy multi-board scraper is an opt-in fallback, and realistic mock listings are the last resort. |
| `pipeline/scoring.py` | Pure `classify_sponsorship()` and `score_job()` — no network, no LLM. |
| `pipeline/drafting.py` | Cover-letter / cold-email generation with the LLM injected as a callable; falls back to offline templates when no key is set. |
| `pipeline/orchestrator.py` | `gather_jobs()` and `run_pipeline()` wire the stages together. |

**Why this changed.** The old pipeline used LinkedIn/Indeed scraping
(python-jobspy) plus HTML board scrapers as its *primary* job source. Those
silently break the moment a site changes markup or rate-limits/CAPTCHAs an
automated client — the classic "0 real jobs, always" failure. The primary
source is now the **Adzuna Job Search API** (official, free tier, UK-focused,
stable JSON contract) with **Reed's official API** as a secondary. Scraping is
kept only as a clearly-labelled, opt-in, best-effort fallback — never the
primary path.

**No keys? It still works.** With no Adzuna/Reed keys the pipeline runs the
full flow on a set of realistic UK supply-chain mock listings, so you can demo
parse -> match -> draft end-to-end before signing up for anything. The run log
states plainly which source was used and where to add keys for live data.

### Environment variables

| Variable | Purpose | Get it free |
| --- | --- | --- |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | **Primary** real UK job data | https://developer.adzuna.com/ |
| `REED_API_KEY` | Secondary UK job data (merged on top of Adzuna) | https://www.reed.co.uk/developers |
| `GROQ_API_KEY` | AI-written cover letters + cold emails (offline templates used if unset) | https://console.groq.com |
| `EMAIL_ADDRESS` + `EMAIL_PASSWORD` | SMTP sender for cold emails (Gmail App Password) | https://myaccount.google.com/apppasswords |

All are optional — none are required to run the full flow on mock data with
offline drafts. Copy `.env.example` to `.env` and fill in what you have.
