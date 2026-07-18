"""Regression tests for the Streamlit-launch step (STEP 4).

Real bug report (earlier round): after conda-detection let the launcher reach
STEP 4 on the user's machine, the backend health-checked 200 OK but Streamlit
never came up -- no browser, no app. Root cause was `--server.headless false`,
which on a FIRST run makes Streamlit print an interactive "Welcome to Streamlit!
Email:" prompt and BLOCK on stdin. `--server.headless true` skips that prompt;
the launcher then opens the browser itself (headless mode won't auto-open one).

The orchestration has since moved OUT of launch_app.bat and into launch.py
(Python is far more reliable for subprocess/polling/error-handling than batch,
which failed across three rounds). So these guards now assert against launch.py,
where the fixed STEP 4 behaviour lives -- the regressions they protect against
(no headless flag, wrong python, no browser-open, no UI poll, broken health
poll) still cannot silently return.
"""
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCH_PY = os.path.join(HERE, "launch.py")
REQ = os.path.join(HERE, "requirements.txt")


def _py_text():
    return open(LAUNCH_PY, encoding="utf-8", errors="replace").read()


def test_streamlit_launched_headless_true():
    """The whole point of the earlier fix: headless TRUE (skips the email prompt)."""
    text = _py_text()
    assert '"--server.headless", "true"' in text
    # The buggy form must never come back.
    assert "headless false" not in text
    assert '"--server.headless", "false"' not in text


def test_streamlit_uses_resolved_python():
    """Streamlit must run under the SAME interpreter as the launcher (sys.executable),
    which is exactly the resolved env python the batch activated -- never a bare
    'python' that could resolve to a different install."""
    text = _py_text()
    # The streamlit command list must lead with sys.executable, not a literal "python".
    assert 'sys.executable, "-m", "streamlit", "run", "app.py"' in text


def test_launcher_opens_browser_itself():
    """Headless mode won't open a browser, so the launcher must open it explicitly."""
    text = _py_text()
    assert "webbrowser.open" in text
    assert "localhost:" in text


def test_launcher_waits_for_ui_port():
    """The launcher must poll the UI port so the browser only opens once it is up."""
    text = _py_text()
    assert "8501" in text
    assert "wait_until_healthy(UI_URL" in text


def test_backend_health_poll_preserved():
    """Guard: the working backend-start + health-poll logic must remain intact."""
    text = _py_text()
    assert "/health" in text
    assert "backend.main:app" in text
    assert "wait_until_healthy(API_HEALTH_URL" in text


def test_requirements_pin_requests_stack():
    """The RequestsDependencyWarning fix: bounded urllib3/charset-normalizer/chardet."""
    req = open(REQ, encoding="utf-8", errors="replace").read()
    assert "urllib3<3" in req
    assert "charset-normalizer<4" in req
    assert "chardet<6" in req
