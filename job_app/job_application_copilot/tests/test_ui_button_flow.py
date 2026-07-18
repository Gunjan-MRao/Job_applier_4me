"""End-to-end UI regression test for the resume-parse -> review -> agent flow.

Guards the bug where clicking "Parse resume" jumped straight to the "Start AI
Agent" step, skipping the parsed-profile review. This test drives the *real*
rendered Streamlit UI with a headless Chromium browser.

It is fully self-contained: it boots the FastAPI backend and the Streamlit app
as subprocesses with a blank .env, then tears them down. It SKIPS (never fails
the suite) if Playwright, the Chromium browser, or the servers are unavailable
in the current environment (e.g. CI without a browser), so the existing offline
test suite stays green.
"""
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

BACKEND_PORT = 8010
UI_PORT = 8511
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
UI_URL = f"http://127.0.0.1:{UI_PORT}"

pytest.importorskip("playwright", reason="playwright not installed")
from playwright.sync_api import sync_playwright, expect  # noqa: E402


def _ensure_docx() -> bool:
    """Create the docx fixture from the txt fixture if needed. Return success."""
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
def servers():
    if not _ensure_docx():
        pytest.skip("could not prepare sample_resume.docx fixture")
    if not (_free(BACKEND_PORT) and _free(UI_PORT)):
        pytest.skip(f"ports {BACKEND_PORT}/{UI_PORT} already in use")

    env_file = APP_DIR / ".env"
    if not env_file.exists():
        example = APP_DIR / ".env.example"
        if example.exists():
            shutil.copyfile(example, env_file)

    procs = []
    try:
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
            cwd=str(APP_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        procs.append(backend)
        ui = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.headless", "true", "--server.port", str(UI_PORT),
             "--server.address", "127.0.0.1"],
            cwd=str(APP_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        procs.append(ui)

        if not _wait_http(f"{BACKEND_URL}/health", 30):
            pytest.skip("backend did not become ready")
        if not _wait_http(f"{UI_URL}/_stcore/health", 40):
            pytest.skip("streamlit did not become ready")
        yield
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()


def test_parse_does_not_skip_to_agent(servers):
    """Parse resume must show the profile review and NOT jump to the agent step."""
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

        # The parsed-profile review must render on the Setup page...
        expect(page.get_by_text("Extracted profile")).to_be_visible(timeout=30000)
        # ...and the agent step must NOT have been auto-entered (the reported bug).
        assert page.get_by_role("button", name="Start AI Agent").count() == 0, \
            "regression: clicking Parse resume skipped straight to 'Start AI Agent'"

        # Advancing is an explicit user action.
        page.get_by_role("button", name="Go to AI Agent").click()
        expect(page.get_by_text("AI Job Agent")).to_be_visible(timeout=30000)

        browser.close()
    finally:
        pw.stop()
