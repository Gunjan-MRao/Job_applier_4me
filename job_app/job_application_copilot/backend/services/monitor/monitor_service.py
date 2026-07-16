from backend.services.monitor.run_store import get_run, list_events


def audit_run(run_id: str) -> dict:
    run = get_run(run_id)
    if not run:
        return {
            "run_id": run_id,
            "workflow_name": "unknown",
            "run_status": "failed",
            "issues": [
                {
                    "severity": "high",
                    "code": "RUN_NOT_FOUND",
                    "message": "Workflow run not found",
                    "step_name": None,
                }
            ],
            "total_events": 0,
            "failed_events": 0,
            "warning_events": 0,
        }

    events = list_events(run_id)
    issues = []
    issue_keys = set()

    failed_events = [e for e in events if e["status"] == "failed"]
    warning_events = [e for e in events if e["status"] == "warning"]

    def add_issue(severity: str, code: str, message: str, step_name: str | None):
        key = (code, message, step_name)
        if key not in issue_keys:
            issue_keys.add(key)
            issues.append(
                {
                    "severity": severity,
                    "code": code,
                    "message": message,
                    "step_name": step_name,
                }
            )

    for e in failed_events:
        add_issue(
            "high",
            "STEP_FAILED",
            e.get("error_text") or e.get("message") or "A workflow step failed",
            e["step_name"],
        )

    for e in warning_events:
        add_issue(
            "medium",
            "STEP_WARNING",
            e.get("message") or "A workflow step raised a warning",
            e["step_name"],
        )

    for e in events:
        output_summary = e.get("output_summary") or {}

        if e["step_name"] == "resume_parse":
            exp = str(output_summary.get("years_of_experience_hint") or "").lower()
            if "9+ years" in exp:
                add_issue(
                    "medium",
                    "EXPERIENCE_SUSPECT",
                    "Experience estimate looks suspicious for an early-career profile",
                    e["step_name"],
                )

            candidate_name = output_summary.get("candidate_name")
            email = output_summary.get("email")
            if not candidate_name or not email:
                add_issue(
                    "high",
                    "PARSE_INCOMPLETE",
                    "Resume parsing missed required candidate fields",
                    e["step_name"],
                )

        if e["step_name"] == "job_search":
            jobs_found = output_summary.get("jobs_found")
            if jobs_found == 0:
                add_issue(
                    "high",
                    "NO_JOBS_FOUND",
                    "Job search returned zero matching jobs",
                    e["step_name"],
                )

        if e["step_name"] == "role_fit":
            fit_score = output_summary.get("fit_score")
            if isinstance(fit_score, (int, float)) and fit_score < 40:
                add_issue(
                    "medium",
                    "LOW_ROLE_FIT",
                    "Candidate-to-role fit score is low",
                    e["step_name"],
                )

        if e["step_name"] == "job_match":
            shortlisted_jobs = output_summary.get("shortlisted_jobs")
            risky_shortlist_jobs = output_summary.get("risky_shortlist_jobs")

            if shortlisted_jobs == 0:
                add_issue(
                    "medium",
                    "NO_SAFE_SHORTLIST",
                    "Job evaluation produced no safe shortlist",
                    e["step_name"],
                )

            if isinstance(risky_shortlist_jobs, int) and risky_shortlist_jobs > 0:
                add_issue(
                    "medium",
                    "RISKY_SHORTLIST",
                    f"Shortlist contains {risky_shortlist_jobs} risky jobs",
                    e["step_name"],
                )

        if e["step_name"] == "resume_tailor":
            missing_keywords = output_summary.get("missing_keywords")
            if isinstance(missing_keywords, int) and missing_keywords >= 8:
                add_issue(
                    "medium",
                    "TAILORING_GAPS",
                    f"Resume tailoring still has {missing_keywords} missing priority keywords",
                    e["step_name"],
                )

        if e["step_name"] == "resume_generate":
            experience_bullets = output_summary.get("experience_bullets")
            if isinstance(experience_bullets, int) and experience_bullets < 3:
                add_issue(
                    "medium",
                    "DRAFT_BULLETS_THIN",
                    "Generated resume draft has limited experience bullet coverage",
                    e["step_name"],
                )

        if e["step_name"] == "resume_save":
            suggested_filename = output_summary.get("suggested_filename")
            if not suggested_filename:
                add_issue(
                    "medium",
                    "RESUME_FILENAME_MISSING",
                    "Saved resume version is missing a suggested filename",
                    e["step_name"],
                )

        if e["step_name"] == "resume_export":
            file_path = output_summary.get("file_path")
            if not file_path:
                add_issue(
                    "medium",
                    "EXPORT_PATH_MISSING",
                    "Resume export completed without a file path",
                    e["step_name"],
                )

        if e["step_name"] == "apply_submit":
            submitted = output_summary.get("submitted")
            if submitted is False:
                add_issue(
                    "high",
                    "APPLICATION_NOT_SUBMITTED",
                    "Application submission did not complete",
                    e["step_name"],
                )

    return {
        "run_id": run["run_id"],
        "workflow_name": run["workflow_name"],
        "run_status": run["status"],
        "issues": issues,
        "total_events": len(events),
        "failed_events": len(failed_events),
        "warning_events": len(warning_events),
    }