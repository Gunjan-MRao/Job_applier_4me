# Deploying to Streamlit Community Cloud

This app runs as a **single process** on Streamlit Community Cloud. There is no
separate backend server to start — the Streamlit UI calls the pipeline logic
(resume parsing, job search, scoring, drafting, the application tracker)
**directly in-process**. This is controlled by the `RUN_MODE` environment
variable, which defaults to `embedded`.

> Local development is unchanged. `launch_app.bat` / `launch.py` still run the
> FastAPI backend, and you can force the HTTP path by setting `RUN_MODE=http`.
> On Streamlit Cloud, leave `RUN_MODE` unset (it defaults to `embedded`).

---

## 1. Push the repo to GitHub

Make sure your fork/repo contains `job_app/job_application_copilot/app.py` and
that **no secrets are committed** (`.env` and `.streamlit/secrets.toml` are both
gitignored — only the `.example` templates are tracked).

## 2. Create the app on Streamlit Community Cloud

1. Go to **https://share.streamlit.io** and sign in with GitHub.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `<your-github-username>/Job_applier_4me`
   - **Branch:** `main`
   - **Main file path:** `job_app/job_application_copilot/app.py`
4. (Optional) Set a custom app URL.

## 3. Add your secrets

Click **Advanced settings → Secrets** (or, after deploy, **⋮ → Settings →
Secrets**) and paste your keys using the **exact key names** from
[`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example):

```toml
GROQ_API_KEY = "gsk_..."
GEMINI_API_KEY = ""
ADZUNA_APP_ID = "your_adzuna_app_id"
ADZUNA_APP_KEY = "your_adzuna_app_key"
REED_API_KEY = "your_reed_api_key"
EMAIL_ADDRESS = ""
EMAIL_PASSWORD = ""
```

All keys are **optional**:

- With **no** `ADZUNA_*` / `REED_API_KEY`, the app runs on built-in **sample**
  job listings and shows a clear red banner saying the data is not live.
- With **no** `GROQ_API_KEY` (or `GEMINI_API_KEY`), cover letters and cold
  emails are generated from solid offline templates instead of an LLM.

`app.py` copies these secrets into the process environment at startup **before**
any backend module is imported, so the same backend code reads them whether they
come from Streamlit secrets, a local `.env`, or real environment variables.
Explicit environment variables / `.env` values always win over secrets, so local
runs are never affected.

## 4. Deploy

Click **Deploy**. Streamlit installs `requirements.txt` and launches
`streamlit run app.py`. The app boots in embedded mode with no backend server.

---

## Known limitation: data does not persist across redeploys

The app stores application-tracker data in a local SQLite database
(`storage/jobs.db`) and writes generated files under `storage/`. Streamlit
Community Cloud uses an **ephemeral filesystem**: this directory is **wiped on
every redeploy, and whenever the app goes to sleep and is restarted**.

What this means in practice:

- A single browsing session works fully: parse a CV, run the agent, review
  matches, and track applications.
- Applications you save **will not survive** an app restart / redeploy.

This is an accepted limitation for the free tier — the app never silently loses
data mid-session, it only resets on a cold restart. To make state durable,
point `DATABASE_URL` at an external managed database (e.g. a hosted Postgres)
via secrets instead of the bundled SQLite file.

---

## Environment variable reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUN_MODE` | `embedded` | `embedded` = in-process (Cloud); `http` = call a local FastAPI backend. |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | _(unset)_ | Primary live UK job source. |
| `REED_API_KEY` | _(unset)_ | Secondary live UK job source. |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | _(unset)_ | LLM for AI-written drafts. |
| `EMAIL_ADDRESS` / `EMAIL_PASSWORD` | _(unset)_ | Optional cold-email sending. |
| `DATABASE_URL` | bundled SQLite | Point at external DB for durable storage. |
