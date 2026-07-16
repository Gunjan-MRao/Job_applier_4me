# 🤖 Adversarial AI Review Brief — Job Applier Pipeline

## 🎯 Mission — URGENT / Time-Sensitive

This project has a **hard deadline: 6 January 2027**.

The candidate’s fiancée holds a **Post-Study Work (PSW) visa** that is ending.
She has a **one-way ticket booked to India on 6 January 2027**.
The sole goal of this application is to secure a **UK Skilled Worker visa-sponsored job**
in **supply chain / logistics / procurement / freight forwarding** before that date.

Every day of pipeline failure = a missed application = closer to the deadline.

---

## 🔍 How to Use This File

Paste the section below into **ChatGPT, Claude, or Gemini** alongside the relevant code files.
Ask each model to critique the code from its assigned lens, then paste the responses back
as PR comments so all three outputs are visible side-by-side.

---

## 💬 Adversarial Prompt (paste into any AI)

```
You are a hostile senior engineer at a UK recruitment technology company.
Your job is to find every reason this pipeline will fail before January 6th 2027.
The candidate’s fiancée needs a Skilled Worker visa-sponsored job in UK supply chain /
logistics before her PSW visa expires and she has to leave the UK.

Review the code I am about to paste and:
1. List the 5 most critical failure modes (file + reason)
2. List 3 architectural changes that would most improve success rate in the next 6 months
3. List 2 things you would reject in a code review that could actively hurt the candidate’s chances
4. Suggest the top 3 UK job boards / channels MISSING from the current pipeline for
   visa-sponsored supply chain roles
5. Advise: should the cover letter mention visa sponsorship needs, or not?
   The current code says DO NOT mention it. Is that right for UK Skilled Worker sponsors?

Code files to review:
- backend/services/automation_runtime.py  (core pipeline)
- backend/services/jobs/scraper.py        (17-board 4-phase scraper)
- backend/services/resume/resume_tailor_service.py
- backend/core/config.py
```

---

## 🔴 Review Lenses

### Lens 1 — Scraper Reliability
- Which boards will 403/rate-limit first?
- Is HTML selector logic fragile to redesigns?
- Is deduplication across 17+ sources good enough?

### Lens 2 — Sponsorship Detection
- Is `classify_sponsorship()` accurate? False negatives = missed sponsored jobs.
- Does `KNOWN_SPONSORS` match company names correctly?
- Are the visa-specific boards actually reliable for UK supply chain?

### Lens 3 — Fit Scoring
- Is `ai_fit_score()` returning meaningful differentiation?
- Is `MIN_FIT_SCORE=10` right, or too low (noise) / too high (misses jobs)?
- Does `title_floor=15` surface genuinely bad jobs?
- Is `senior_penalty` protecting correctly against Director/VP roles?

### Lens 4 — Cover Letter Strategy
- The code says **“Do NOT mention visa sponsorship”** in cover letters.
  Is this right? UK employers who can sponsor need to know upfront to trigger
  the Home Office CoS process.
- Is the offline fallback cover letter too generic?
- Are 120-word cold emails right for UK supply chain recruiters?

### Lens 5 — Architecture
- SQLite for multi-run persistence — is this a bottleneck?
- In-memory `RUNS` dict lost on server restart — acceptable?
- `ThreadPoolExecutor(max_workers=12)` for scraping — too aggressive, risk of IP ban?
- No rate limiting between boards — will the app get blocked?

### Lens 6 — Deadline Risk / Coverage Gaps
- Which boards are most important for the Jan 6 deadline?
- Missing any major UK visa-sponsorship channels for supply chain?
- Should high-scoring jobs get more tailored treatment vs bulk approach?
- Should the pipeline target known Tier-2 sponsors in SC more aggressively?

### Lens 7 — Legal & Ethical Risks
- Is automated bulk cold-emailing legally/ethically problematic in the UK?
- Could mass emails cause recruiter blacklisting of the candidate?
- GDPR concerns with storing job listings + recruiter emails in SQLite?

---

## ✅ Audit Checklist

- [ ] Copilot inline review done
- [ ] ChatGPT critique pasted as PR comment (Lens 1 + 2)
- [ ] Claude critique pasted as PR comment (Lens 3 + 4)
- [ ] Gemini critique pasted as PR comment (Lens 5 + 6 + 7)
- [ ] Critical failures triaged and issues created
- [ ] Sponsorship detection accuracy confirmed
- [ ] Cover letter strategy confirmed or updated
- [ ] Missing job boards identified and added

---

> ⏰ **Time context**: PSW visa ends early 2027. One-way ticket to India booked 6 Jan 2027.
> This is not a hobby project.
