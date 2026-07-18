# First-time setup (Windows)

## 1. Pull latest code
In GitHub Desktop: **Fetch origin** → **Pull origin**

## 2. Create the `jobcopilot` conda environment (once)
Open the **Anaconda Prompt** and run:
```
conda create -n jobcopilot python=3.12 -y
conda activate jobcopilot
cd job_app\job_application_copilot
pip install -r requirements.txt
copy .env.example .env
```

> The environment **must** be named `jobcopilot` — the launcher activates that
> exact name. If it is missing, `launch_app.bat` prints the command above.

## 3. Run the app — just double-click `launch_app.bat`
In `job_app\job_application_copilot\`, double-click **`launch_app.bat`**. It:

1. activates the `jobcopilot` environment,
2. checks/installs dependencies,
3. starts the backend API and **waits until it is healthy**,
4. starts Streamlit and opens your browser at http://localhost:8501.

If anything fails, the window stays open with a clear error (it will not flash
and close). A separate "JobCopilot Backend" window shows the API log, also saved
to `backend_startup.log`.

**Not on plain Windows cmd?** (macOS / Linux / Git-Bash) run the same steps via:
```
./launch_app.sh
```

**Manual fallback** (if the launcher misbehaves):
```
conda activate jobcopilot
cd job_app\job_application_copilot
uvicorn backend.main:app --reload    (in one terminal)
streamlit run app.py                 (in another terminal)
```

## 5. How to use it

1. **⚙️ Setup tab** — Upload your CV (PDF or DOCX). Works immediately, no backend needed.
2. **▶ Start** button in the sidebar — starts the backend API server.
3. **🤖 AI Agent tab** — click **Start AI Agent**. It will:
   - Start the backend automatically if not already running
   - Scrape LinkedIn, Indeed, Glassdoor, Reed, NHS, GOV.UK jobs in parallel
   - Score every job against your resume (0-100% fit score)
   - Filter out jobs with no visa sponsorship
   - Generate a cover letter for each strong match
   - Show live log, progress bar, and top matches
4. **📋 Applications tab** — track the status of each application
5. **🩺 Health tab** — if something is broken, this shows exactly what package is missing

## Troubleshooting

**Launcher says it can't activate `jobcopilot`?**
- The env doesn't exist yet. Run: `conda create -n jobcopilot python=3.12 -y`
  then `conda activate jobcopilot` and `pip install -r requirements.txt`.

**Launcher says it can't find conda?**
- Open the **Anaconda Prompt** once and run `conda init cmd.exe`, then close and
  re-run `launch_app.bat`.

**Backend won't start?**
- Look at the "JobCopilot Backend" window the launcher opened — the exact error
  is printed there (and in `backend_startup.log`).
- Or open the 🩺 Health tab — it shows the startup log with the exact error.
- Most common cause: missing packages. Run `pip install -r requirements.txt` again.

**Resume not parsing?**
- Make sure `pypdf` and `python-docx` are installed
- Try: `pip install pypdf python-docx`

**No jobs found?**
- Install jobspy: `pip install python-jobspy`
- Check the 🩺 Health tab to confirm it shows ✅
