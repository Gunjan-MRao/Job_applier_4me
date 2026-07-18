"""Regression test for the Streamlit-launch step (STEP 4) of launch_app.bat.

Real bug report: after the conda-detection fix let the launcher finally reach
STEP 4 on the user's machine, the backend started and health-checked 200 OK but
Streamlit never came up -- no browser, no app.

Root cause: STEP 4 ran

    python -m streamlit run app.py --server.port 8501 --server.headless false

On a FIRST run, `--server.headless false` makes Streamlit print an interactive
"Welcome to Streamlit!  Email:" prompt and then BLOCK on stdin waiting for input.
From a double-clicked .bat that looks like nothing happened. `--server.headless
true` skips that prompt and starts immediately; the launcher then opens the
browser itself (headless mode does not auto-open one).

These tests guard the fixed STEP 4 so the regression cannot silently return.
"""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(HERE, "launch_app.bat")
REQ = os.path.join(HERE, "requirements.txt")


def _bat_text():
    return open(BAT, encoding="utf-8", errors="replace").read()


def test_streamlit_launched_headless_true():
    """The whole point of the fix: headless TRUE (skips the blocking email prompt)."""
    text = _bat_text()
    assert "--server.headless true" in text
    # The buggy form must be gone.
    assert "--server.headless false" not in text


def test_streamlit_uses_resolved_python():
    """Streamlit must use the same resolved full python path the backend uses."""
    text = _bat_text()
    # Find the streamlit-run line and confirm it invokes "!PYTHON_EXE!", not bare python.
    line = next(l for l in text.splitlines() if "streamlit run app.py" in l)
    assert "!PYTHON_EXE!" in line


def test_launcher_opens_browser_itself():
    """Headless mode won't open a browser, so the launcher must open it explicitly."""
    text = _bat_text()
    assert 'start "" "http://localhost:%UI_PORT%"' in text


def test_launcher_waits_for_ui_port():
    """STEP 4 should poll the UI port so we only open the browser once it is up."""
    text = _bat_text()
    # A PowerShell poll against the UI port, mirroring the backend health poll.
    assert "127.0.0.1:%UI_PORT%" in text


def test_backend_health_poll_preserved():
    """Guard: the working backend-start + health-poll logic must remain intact."""
    text = _bat_text()
    assert "127.0.0.1:%API_PORT%/health" in text
    assert "uvicorn backend.main:app" in text


def test_requirements_pin_requests_stack():
    """The RequestsDependencyWarning fix: bounded urllib3/charset-normalizer/chardet."""
    req = open(REQ, encoding="utf-8", errors="replace").read()
    assert "urllib3<3" in req
    assert "charset-normalizer<4" in req
    assert "chardet<6" in req
