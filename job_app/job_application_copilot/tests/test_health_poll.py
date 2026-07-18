"""Regression tests for the health-poll logic in launch_app.bat (STEP 3 + STEP 4).

Real bug report (real Windows machine, two windows observed):
  * "JobCopilot Backend" window: uvicorn up, "Application startup complete",
    and 127.0.0.1 - "GET /health HTTP/1.1" 200 OK  -> backend genuinely healthy.
  * ORIGINAL launcher window: stuck forever at "Waiting for the backend to become
    healthy..." -- never prints "Backend is healthy.", never reaches [4/4].

The old poll used a `powershell -Command "... Invoke-WebRequest ..."` one-liner.
It got a successful 200 but control never returned to cmd.exe (a Windows
PowerShell 5.1-specific hang). The fix replaces it with a plain batch retry loop
around curl.exe (built into Windows 10 1803+/11), with PowerShell kept only as a
fallback for boxes without curl.exe.

These tests:
  1. Encode the exact retry-loop semantics (curl -s -o nul -w "%{http_code}"
     --connect-timeout 2 --max-time 5) as a Python `poll_url` mirror and prove it
     detects 200 promptly, times out cleanly on a dead port, and waits for a
     slow-starting server -- and never hangs.
  2. Guard launch_app.bat so the curl-based :poll_url (and the PowerShell
     fallback) cannot silently regress back to an inline blocking one-liner.
"""
import http.server
import os
import shutil
import socket
import subprocess
import threading
import time

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(HERE, "launch_app.bat")

CURL = shutil.which("curl")
pytestmark = pytest.mark.skipif(CURL is None, reason="curl not available to mirror curl.exe")


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


def _serve(port, ready_evt=None, delay=0.0):
    if delay:
        time.sleep(delay)
    httpd = http.server.HTTPServer(("127.0.0.1", port), _Quiet)
    if ready_evt is not None:
        ready_evt.set()
    httpd.serve_forever()
    return httpd


def poll_url(url, max_seconds):
    """1:1 mirror of the batch :poll_url loop (curl.exe primary path).

    Returns (ok, elapsed_seconds). ok mirrors POLL_OK being set.
    """
    start = time.monotonic()
    for _ in range(max_seconds):
        code = subprocess.run(
            [CURL, "-s", "-o", os.devnull, "-w", "%{http_code}",
             "--connect-timeout", "2", "--max-time", "5", url],
            capture_output=True, text=True,
        ).stdout.strip()
        if code == "200":
            return True, time.monotonic() - start
        time.sleep(1)
    return False, time.monotonic() - start


def test_detects_200_promptly_on_running_server():
    port = _free_port()
    srv = http.server.HTTPServer(("127.0.0.1", port), _Quiet)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        ok, elapsed = poll_url(f"http://127.0.0.1:{port}/", 30)
        assert ok is True
        assert elapsed < 3, f"should detect an up server almost immediately (took {elapsed:.1f}s)"
    finally:
        srv.shutdown()


def test_times_out_cleanly_on_dead_port():
    port = _free_port()  # nothing ever listens here
    start = time.monotonic()
    ok, elapsed = poll_url(f"http://127.0.0.1:{port}/", 3)
    wall = time.monotonic() - start
    assert ok is False, "must report failure (caller prints the error) rather than hang"
    assert wall < 20, f"must not hang; bounded retry budget (took {wall:.1f}s)"


def test_waits_for_slow_starting_server_then_succeeds():
    port = _free_port()
    ready = threading.Event()

    def run():
        time.sleep(5)  # server starts listening only after 5s
        srv = http.server.HTTPServer(("127.0.0.1", port), _Quiet)
        ready.set()
        srv.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    ok, elapsed = poll_url(f"http://127.0.0.1:{port}/", 30)
    assert ok is True, "loop must keep polling and succeed once the server comes up"
    assert elapsed >= 4, f"should have waited for the slow start (took {elapsed:.1f}s)"


# --- Static guards on the .bat itself --------------------------------------

def _bat_text():
    return open(BAT, encoding="utf-8", errors="replace").read()


def test_bat_uses_curl_based_poll_subroutine():
    text = _bat_text()
    assert ":poll_url" in text                       # shared poll subroutine exists
    assert "call :poll_url" in text                  # STEP 3/4 call it
    assert "curl.exe" in text                        # curl.exe is the primary path
    assert "%{http_code}" in text                    # status-code check via curl
    assert "--connect-timeout" in text and "--max-time" in text  # bounded, no hang


def test_bat_keeps_powershell_only_as_fallback():
    text = _bat_text()
    # PowerShell must survive ONLY inside the fallback branch of :poll_url,
    # not as the STEP 3/4 inline poll. There should be exactly one powershell
    # invocation left (the fallback), and it must sit after the :poll_url label.
    assert text.count("powershell -NoProfile") == 1
    assert text.index(":poll_url") < text.index("powershell -NoProfile")


def test_bat_callers_check_poll_ok():
    text = _bat_text()
    # STEP 3 and STEP 4 each call the subroutine and gate on POLL_OK.
    assert text.count("call :poll_url") == 2
    # Each call site is immediately followed by the POLL_OK gate.
    lines = text.splitlines()
    call_idxs = [i for i, l in enumerate(lines) if "call :poll_url" in l]
    for i in call_idxs:
        assert "if not defined POLL_OK" in lines[i + 1], \
            f"call :poll_url at line {i+1} is not gated by 'if not defined POLL_OK'"
