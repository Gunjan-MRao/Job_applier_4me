# First-time setup (Windows)

## 1. Pull latest code
In GitHub Desktop: **Fetch origin** → **Pull origin**

## 2. Open a terminal in the project folder
In GitHub Desktop: **Repository → Open in Command Prompt**

Then:
```
cd job_app\job_application_copilot
```

## 3. Install all packages
```
pip install -r requirements.txt
```

If you see errors about jobspy or openai:
```
pip install python-jobspy openai anthropic pypdf python-docx
```

## 4. Run the app
```
streamlit run app.py
```

The browser will open automatically at http://localhost:8501

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

**Backend won't start?**
- Go to the 🩺 Health tab — it shows the startup log with the exact error
- Most common cause: missing packages. Run `pip install -r requirements.txt` again.

**Resume not parsing?**
- Make sure `pypdf` and `python-docx` are installed
- Try: `pip install pypdf python-docx`

**No jobs found?**
- Install jobspy: `pip install python-jobspy`
- Check the 🩺 Health tab to confirm it shows ✅
