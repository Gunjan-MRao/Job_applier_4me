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
