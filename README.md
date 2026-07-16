# Job Application Copilot

An AI-powered job application automation tool built for UK job seekers who need visa sponsorship.

## Features

| Feature | Status |
|---|---|
| Resume parsing (PDF/DOCX) | ✅ Live |
| Multi-source job scraping (LinkedIn, Indeed, Glassdoor, Google, Reed, NHS, GOV.UK…) | ✅ Live |
| Parallel scraping (4× faster) | ✅ Live |
| AI job fit scoring (title + skills + seniority + location + sponsorship) | ✅ Live |
| LLM cover letter generation (OpenAI / Anthropic / offline fallback) | ✅ Live |
| Company blacklist / whitelist filters | ✅ Live |
| Live run monitor with log stream | ✅ Live |
| Application tracker (status, notes) | ✅ Live |
| Portable setup — works on any machine, any path | ✅ Live |

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/Gunjan-MRao/Job_applier_4me.git
cd Job_applier_4me/job_app/job_application_copilot
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and add OPENAI_API_KEY or ANTHROPIC_API_KEY (optional)

# 3. Run the app
streamlit run app.py
# Then click "▶ Start" in the sidebar to launch the backend
```

## How it works

1. **⚙️ Setup tab** — Upload your CV. The parser extracts your name, email, skills, and target roles.
2. **🔴 Live Monitor** — Keywords auto-filled from your resume. Click **🚀 Start run**.
   - JobSpy scrapes LinkedIn, Indeed, Glassdoor, and Google in parallel
   - Reed, CV-Library, TotalJobs, NHS Jobs, FindAJob.gov, and UK Visa Sponsorship boards scraped in parallel
   - Each job is AI-scored against your profile (fit score 0–100)
   - Jobs with sponsorship=`no` are filtered out automatically
   - Cover letters generated via GPT-4o-mini or Claude Haiku (falls back to a template offline)
3. **🏆 Top Matches** — See the top 20 jobs ranked by fit score with direct links
4. **📋 Applications** — Track status (draft → submitted → interview)

## Project structure

```
job_app/
├── job_application_copilot/
│   ├── app.py                          # Streamlit frontend
│   ├── requirements.txt
│   ├── .env.example
│   └── backend/
│       ├── main.py                     # FastAPI app
│       ├── core/config.py              # Settings (pydantic-settings)
│       ├── api/v1/endpoints/           # All API routes
│       ├── services/
│       │   ├── automation_runtime.py   # Pipeline orchestrator
│       │   ├── match/job_fit_service.py
│       │   ├── match/role_fit_service.py
│       │   ├── parser/resume_parser.py
│       │   └── resume/resume_tailor_service.py
│       └── schemas/
│           └── automation.py
└── jobspy_service/
    └── jobspy_api.py                   # Optional sidecar (not required any more)
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Optional | Enables GPT-4o-mini cover letters |
| `ANTHROPIC_API_KEY` | Optional | Enables Claude Haiku cover letters |
| `DATABASE_URL` | No | Defaults to SQLite in project dir |

## Inspired by

- [feder-cr/Jobs_Applier_AI_Agent_AIHawk](https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk) — AI form-filling and persona approach
- [GodsScion/Auto_job_applier_linkedIn](https://github.com/GodsScion/Auto_job_applier_linkedIn) — LinkedIn Easy Apply automation
- [wodsuz/EasyApplyJobsBot](https://github.com/wodsuz/EasyApplyJobsBot) — Multi-platform Easy Apply
- [python-jobspy/python-jobspy](https://github.com/Bunsly/JobSpy) — Unified job board scraper
