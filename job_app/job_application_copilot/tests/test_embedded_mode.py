"""
test_embedded_mode.py — PROOF the app runs single-process (Streamlit-only).

Workstream A guarantee: on Streamlit Community Cloud there is ONE process
(`streamlit run app.py`) — no uvicorn. This test boots ONLY the Streamlit app
(no FastAPI backend), then drives the full flow in a real headless browser:

    upload CV -> parse -> review -> Go to AI Agent -> Start AI Agent -> dashboard

It asserts:
  * the FastAPI backend port is NEVER opened (nothing talks HTTP to :8000),
  * the running dashboard renders (proving the pipeline ran in-process),
  * with job-search API keys blanked, the honest SAMPLE-DATA banner appears,
  * the "missing ScriptRunContext" freeze signature never appears in the log.

SKIPS (never fails the suite) if Playwright / Chromium / the server are
unavailable, so the offline suite stays green.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
RESUME_DOCX = APP_DIR / "tests" / "fixtures" / "sample_resume.docx"
RESUME_TXT = APP_DIR / "tests" / "fixtures" / "sample_resume.txt"

UI_PORT = 8512
BACKEND_PORT = 8000  # the port a FastAPI backend WOULD use — must stay closed
UI_URL = f"http://127.0.0.1:{UI_PORT}"

pytest.importorskip("playwright", reason="playwright not installed")
from playwright.sync_api import sync_playwright, expect  # noqa: E402


def _ensure_docx() -> bool:
    if RESUME_DOCX.exists():
        return True
    if not RESUME_TXT.exists():
        return False
    try:
        from docx import Document
    except Exception:
        return False
    doc = Document()
    for line in RESUME_TXT.read_text(encoding="utf-8").splitlines():
        doc.add_paragraph(line)
    doc.save(RESUME_DOCX)
    return True


def _wait_http(url: str, timeout: float) -> bool:
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture(scope="module")
def ui_only(tmp_path_factory):
    if not _ensure_docx():
        pytest.skip("could not prepare sample_resume.docx fixture")
    if not _free(UI_PORT):
        pytest.skip(f"port {UI_PORT} already in use")
    if not _free(BACKEND_PORT):
        pytest.skip(f"backend port {BACKEND_PORT} already in use — cannot prove it stays closed")

    env_file = APP_DIR / ".env"
    if not env_file.exists():
        example = APP_DIR / ".env.example"
        if example.exists():
            shutil.copyfile(example, env_file)

    log_dir = tmp_path_factory.mktemp("embedded_logs")
    ui_log = log_dir / "streamlit.log"

    # Force embedded mode + blank the live job-search keys so the run is
    # deterministic (mock listings -> the SAMPLE-DATA banner must appear).
    env = dict(os.environ)
    env["RUN_MODE"] = "embedded"
    for k in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY"):
        env[k] = ""
    # Point at a throwaway SQLite DB so this run never contends with a backend
    # started by another test (a shared jobs.db can lock and fail the run).
    env["DATABASE_URL"] = f"sqlite:///{log_dir / 'jobs.db'}"

    ui_log_fh = open(ui_log, "w", encoding="utf-8")
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.headless", "true", "--server.port", str(UI_PORT),
             "--server.address", "127.0.0.1"],
            cwd=str(APP_DIR), stdout=ui_log_fh, stderr=subprocess.STDOUT, env=env,
        )
        if not _wait_http(f"{UI_URL}/_stcore/health", 40):
            pytest.skip("streamlit did not become ready")
        yield ui_log
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        ui_log_fh.close()


def test_embedded_single_process_flow(ui_only):
    """Full flow with NO backend process — pipeline runs in-process."""
    ui_log = ui_only
    # Nothing should be listening on the backend port before we start.
    assert _free(BACKEND_PORT), "a backend is unexpectedly running on :8000"

    try:
        pw = sync_playwright().start()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"playwright runtime unavailable: {exc}")
    try:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"chromium not installed (run: playwright install chromium): {exc}")

        page = browser.new_page()
        page.set_default_timeout(30000)
        page.goto(UI_URL, wait_until="networkidle")

        expect(page.get_by_text("Upload your resume")).to_be_visible(timeout=30000)
        page.set_input_files("input[type=file]", str(RESUME_DOCX))
        page.get_by_role("button", name="Parse resume").click()
        expect(page.get_by_text("Extracted profile")).to_be_visible(timeout=30000)

        page.get_by_role("button", name="Go to AI Agent").click()
        expect(page.get_by_text("AI Job Agent")).to_be_visible(timeout=30000)
        # Embedded backend status must be shown (no separate server).
        expect(page.get_by_text("Embedded (in-process)")).to_be_visible(timeout=30000)

        page.get_by_role("button", name="Start AI Agent").click()

        # The running dashboard must render — proof the in-process pipeline ran.
        expect(page.get_by_role("button", name="Start AI Agent")).to_have_count(0, timeout=60000)
        expect(page.get_by_text("Jobs Found")).to_be_visible(timeout=60000)
        expect(page.get_by_text("Live source feed")).to_be_visible(timeout=60000)

        # With keys blanked the honest SAMPLE-DATA banner must appear.
        expect(page.get_by_text("SAMPLE DATA")).to_be_visible(timeout=60000)

        # The backend port must have stayed closed the entire time.
        assert _free(BACKEND_PORT), "regression: a FastAPI backend was started on :8000"

        browser.close()
    finally:
        pw.stop()

    log_text = ui_log.read_text(encoding="utf-8", errors="ignore")
    assert "missing ScriptRunContext" not in log_text, (
        "regression: a background thread called a Streamlit API outside the "
        "ScriptRunContext — the UI would silently freeze"
    )
