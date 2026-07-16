# 🧠 Multi-Agent Sponsor Strategy Engine

## What This Does

Every job found by the scraper now goes through a **multi-LLM agent debate** before a cover letter is written or an application is sent. The agents argue about whether to apply — then a synthesis agent produces a final action plan.

---

## Research Basis

All logic is grounded in real community discussions (2025–2026):

| Source | Key Insight |
|--------|------------|
| Reddit r/SkilledWorkerVisaUK | Only target GOV.UK licensed sponsors. Disclose at first interaction. |
| Reddit r/IndiansInUK | 5 LinkedIn conversations/day (curiosity, not job begging). Psychometric prep critical. |
| LinkedIn (Farhoon Asim) | 100 targeted companies > 1000 random apps. Follow up every 5 days. |
| LinkedIn (Oliver Cordingley) | Bring up visa on call 1-2. Frame as logistics. Never apologise. |
| YouTube / UKShuke 2026 | Peak hiring: Jan–Mar and Apr–Jun. August = dead zone. |
| Sponso.co.uk / sponsormyvisa.com | Cross-reference GOV.UK register + recent CoS usage data. |

---

## The 5 Agents

| Agent | Persona | Provider | Focus |
|-------|---------|----------|-------|
| Optimist | Upside, fit, company growth signals | Gemini 1.5 Flash | Why to apply |
| Realist | Salary thresholds, competition, effort ROI | HuggingFace Mistral | Hard numbers |
| Tactician | Exact outreach wording, ATS bypass, timing | GPT-4o-mini | How to apply |
| Risk Analyst | Visa risk, company tier, fallback | Claude Haiku | What could go wrong |
| Reddit Oracle | Pattern-matched community rules | Rule-based | Community wisdom |

---

## Company Tier System

| Tier | Meaning | Action |
|------|---------|--------|
| 🏆 Tier 1 | GOV.UK verified + known active recent sponsor | Apply now |
| ✅ Tier 2 | GOV.UK verified (recent CoS activity unknown) | Apply, verify first |
| ⚠️ Tier 3 | Not on GOV.UK register | Skip unless you can verify |

---

## ATS Bypass

Many ATS systems auto-reject candidates who answer `Yes` to _"Do you require visa sponsorship?"_

**Smart answer:** `"I am eligible to work in the UK and would discuss right-to-work arrangements at interview stage."`

This is truthful (you WILL be eligible once sponsored) and gets you to a human. Always clarify in the cover letter and on first call.

---

## Hiring Windows

| Month | Quality | Notes |
|-------|---------|-------|
| Jan–Mar | 🟢 PEAK | New budgets, highest sponsor hiring |
| Apr–Jun | 🟢 PEAK | Graduate intake season |
| Jul | 🟡 OK | Summer slowdown starts |
| Aug | 🔴 SLOW | Hiring freeze at most firms |
| Sep–Oct | 🟡 GOOD | Post-summer ramp-up |
| Nov | 🟡 OK | Slowing toward year-end |
| Dec | 🔴 SLOW | Holiday freeze |

---

## LinkedIn Outreach Strategy

Per Reddit r/IndiansInUK success story:
> _"I began reaching out asking for a 15-min chat to learn about their path — not asking for a job. Just insight."_

The `generate_linkedin_outreach()` function generates curiosity-driven messages. Never asks for a job. Never mentions visa.

---

## Follow-Up Schedule

Per Reddit/LinkedIn coaches: follow up **every 5 days**, maximum 3 times.

- Day 5: Soft follow-up (still interested, any update?)
- Day 10: Brief check-in
- Day 15: Final message (leave door open)

---

## Integration with automation_runtime.py

The `enrich_jobs_with_strategy()` function is called after job scraping in the main pipeline. Each job gets:

- `strategy.synthesis` — final action plan
- `strategy.consensus_confidence` — 0–100 score
- `strategy.company_tier` — Tier 1/2/3
- `strategy.govuk_verified` — True/False/None
- `strategy.linkedin_outreach` — ready-to-send LinkedIn message
- `strategy.followup_schedule` — 3 follow-up email drafts
- `strategy.ats_bypass` — ATS bypass wording
