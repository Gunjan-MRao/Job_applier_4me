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

## First run

```bash
conda activate jobhunter
cd "C:\Users\User\Downloads\job_app\job_application_copilot"
pip install -r requirements.txt
copy .env.example .env
uvicorn backend.main:app --reload
```

Then open:
- API root: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/health
- Docs: http://127.0.0.1:8000/docs
