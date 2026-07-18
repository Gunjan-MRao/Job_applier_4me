"""Regression tests for the Python launcher's health-poll + crash detection.

Background
----------
Orchestration moved out of launch_app.bat (which failed across three rounds:
PowerShell hang, Streamlit headless block, and finally a silent window-vanish
from a curl.exe batch control-flow bug) into launch.py, where polling uses only
urllib and every failure surfaces a real traceback.

These tests pin the two behaviours the batch versions kept getting wrong:
  1. wait_until_healthy detects a 200 promptly, waits for a slow-starting server,
     and times out cleanly on a server that never comes up -- never hanging.
  2. It detects an immediately-crashing subprocess via proc.poll() within ~1s
     (return code reported) instead of blocking for the whole timeout budget.

Plus static guards that launch_app.bat now hands off to launch.py and no longer
carries the old curl.exe/PowerShell inline poll, and that launch.py wraps its
body so the console can never silently close on error.
"""
import http.server
import os
import socket
import subprocess
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import launch  # noqa: E402

BAT = os.path.join(HERE, "launch_app.bat")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


# --- wait_until_healthy: happy path / slow start / timeout -------------------

def test_detects_200_promptly():
    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port), _Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        start = time.monotonic()
        ok, reason = launch.wait_until_healthy(f"http://127.0.0.1:{port}/", max_seconds=30)
        elapsed = time.monotonic() - start
        assert ok is True and reason == "healthy"
        assert elapsed < 3, f"should detect an up server quickly (took {elapsed:.1f}s)"
    finally:
        srv.shutdown()


def test_waits_for_slow_start_then_succeeds():
    port = _free_port()

    def run():
        time.sleep(4)  # only starts listening after 4s
        srv = http.server.HTTPServer(("127.0.0.1", port), _Quiet)
        srv.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    start = time.monotonic()
    ok, reason = launch.wait_until_healthy(f"http://127.0.0.1:{port}/", max_seconds=30)
    elapsed = time.monotonic() - start
    assert ok is True and reason == "healthy"
    assert elapsed >= 3, f"should have waited for the slow start (took {elapsed:.1f}s)"


def test_times_out_cleanly_on_dead_port():
    port = _free_port()  # nothing ever listens
    start = time.monotonic()
    ok, reason = launch.wait_until_healthy(f"http://127.0.0.1:{port}/", max_seconds=3)
    wall = time.monotonic() - start
    assert ok is False
    assert "timeout" in reason
    assert wall < 15, f"must not hang; bounded budget (took {wall:.1f}s)"


# --- crash detection --------------------------------------------------------

def test_detects_immediate_process_crash_fast():
    """A subprocess that exits at once must be reported in ~1s, not the full 30s."""
    port = _free_port()  # never served
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    start = time.monotonic()
    ok, reason = launch.wait_until_healthy(
        f"http://127.0.0.1:{port}/", proc=proc, max_seconds=30
    )
    elapsed = time.monotonic() - start
    assert ok is False
    assert "process exited" in reason
    assert "7" in reason, f"return code should be surfaced: {reason!r}"
    assert elapsed < 10, f"crash must be detected fast, not after timeout (took {elapsed:.1f}s)"


def test_healthy_before_crash_still_reports_healthy():
    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port), _Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # A process that stays alive the whole time.
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ok, reason = launch.wait_until_healthy(
            f"http://127.0.0.1:{port}/", proc=proc, max_seconds=10
        )
        assert ok is True and reason == "healthy"
    finally:
        srv.shutdown()
        proc.terminate()


def test_http_status_returns_none_on_refused():
    port = _free_port()  # nothing listening
    assert launch.http_status(f"http://127.0.0.1:{port}/", timeout=1) is None


# --- static guards on launch_app.bat ----------------------------------------

def _bat_text():
    return open(BAT, encoding="utf-8", errors="replace").read()


def test_bat_hands_off_to_python_launcher():
    text = _bat_text()
    assert "launch.py" in text, "batch must delegate orchestration to launch.py"
    assert "call " in text and "launch.py" in text


def test_bat_no_longer_polls_with_curl_or_powershell():
    text = _bat_text()
    # The fragile inline health-poll machinery must be gone from the batch file.
    assert ":poll_url" not in text
    assert "curl.exe" not in text
    assert "Invoke-WebRequest" not in text
    assert "powershell" not in text.lower()


def test_bat_keeps_conda_detection():
    # STEP 0 conda logic must remain untouched (confirmed working on real machine).
    text = _bat_text()
    for label in (":scan_root", ":check_dir", ":scan_registry"):
        assert label in text, f"conda-detection subroutine {label} missing"
    assert "CONDA_BASE" in text


def test_bat_always_pauses_so_window_cannot_vanish():
    text = _bat_text()
    assert "pause" in text


# --- static guards on launch.py ---------------------------------------------

def _py_text():
    return open(os.path.join(HERE, "launch.py"), encoding="utf-8", errors="replace").read()


def test_launcher_wraps_body_and_pauses_on_error():
    text = _py_text()
    assert "traceback.print_exc" in text, "uncaught errors must print a traceback"
    assert "Press Enter to exit" in text, "console must not vanish on error"
    assert "except Exception" in text
