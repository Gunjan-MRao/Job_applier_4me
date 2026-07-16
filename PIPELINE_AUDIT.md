# Pipeline Audit Notes

This file tracks open questions and known issues surfaced during the adversarial review.
Update this file as issues are confirmed, dismissed, or fixed.

## Open Questions

| # | Area | Question | Status |
|---|------|----------|--------|
| 1 | Scraper | Which boards return 0 results most often? | 🔴 Unknown |
| 2 | Sponsorship | Is `classify_sponsorship()` tested against real job descriptions? | 🔴 Unknown |
| 3 | Cover Letter | Should visa needs be mentioned in cover letter? | 🔴 Debated |
| 4 | Rate Limiting | Is there any per-board delay to prevent IP bans? | 🔴 None currently |
| 5 | Missing boards | Are UK Tier-2 specific boards (e.g. WorkPermit.com, UKHired) covered? | 🔴 Partial |
| 6 | Scoring | Min fit score 10 — is this causing too many weak matches? | 🔴 Unknown |
| 7 | DB | RUNS dict lost on restart — is SQLite sync wired in? | 🔴 Partial |

## Confirmed Issues

_None yet. Fill in after first AI review round._

## Resolved

_None yet._
