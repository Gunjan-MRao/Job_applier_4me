"""Job Application Copilot -- Python launcher (STEP 1 through STEP 4).

Why this file exists
--------------------
The old orchestration lived entirely inside launch_app.bat. Windows batch turned
out to be a fragile foundation for subprocess orchestration and health-polling:

  * Round 1: Streamlit's first-run interactive prompt blocked the launcher
    (fixed with --server.headless true).
  * Round 2: the `powershell Invoke-WebRequest` health poll got a 200 but never
    returned control to cmd.exe -- the launcher hung forever (Windows PowerShell
    5.1-specific behaviour).
  * Round 3: the curl.exe-based batch retry loop caused the launcher window to
    silently *vanish* -- a batch control-flow/quoting failure that terminated
    cmd.exe before a single health request was even logged, with no traceback.

Each round was a new batch-specific failure mode with no error surfaced. Python
has vastly more reliable subprocess/polling/error-handling primitives, and -- the
whole point here -- any failure prints a real traceback instead of a window
disappearing. So all of STEP 1..4 now lives here. launch_app.bat keeps ONLY the
proven conda-detection/activation (STEP 0) and then calls this script.

Everything in run() is wrapped so the console can never silently close on error.
Health polling uses only urllib from the stdlib -- no curl, no PowerShell, no
extra dependency -- and checks proc.poll() every iteration so an immediately
crashing server is reported in ~1s instead of after the full timeout.
"""
import atexit
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
API_HOST = "127.0.0.1"
API_PORT = 8000
UI_PORT = 8501
API_HEALTH_URL = f"http://{API_HOST}:{API_PORT}/health"
UI_URL = f"http://{API_HOST}:{UI_PORT}/"
REQUIRED = ("streamlit", "fastapi", "uvicorn")

# Subprocesses we start, terminated on exit via atexit.
_CHILDREN: list[subprocess.Popen] = []


# ---------------------------------------------------------------------------
# HTTP polling + crash detection (importable / unit-tested)
# ---------------------------------------------------------------------------

def http_status(url: str, timeout: float = 3.0):
    """Return the HTTP status code for a GET, or None if the request failed.

    A 200 means "up". Any connection error / timeout / non-200 returns None so
    the caller simply keeps polling -- it never raises, so the loop cannot die on
    a transient "connection refused" while the server is still starting.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.getcode()
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def wait_until_healthy(url, proc=None, max_seconds=30, interval=1.0, on_tick=None):
    """Poll `url` once/second until it returns 200 or the budget is exhausted.

    Returns (ok, reason):
      * (True, "healthy")                     -- got a 200 within the budget.
      * (False, "process exited (code N)")    -- `proc` died before becoming
        healthy; detected via proc.poll() each iteration so an immediate crash is
        reported in ~1s instead of waiting the full `max_seconds`.
      * (False, "timeout after Ns")           -- never became healthy in time.

    `on_tick(attempt, code)` is an optional progress callback.
    """
    deadline = time.monotonic() + max_seconds
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        # Crash detection first: if the child already exited, stop immediately.
        if proc is not None and proc.poll() is not None:
            return False, f"process exited (code {proc.returncode})"
        code = http_status(url)
        if on_tick is not None:
            on_tick(attempt, code)
        if code == 200:
            return True, "healthy"
        time.sleep(interval)
    # One last crash check so a race at the deadline is reported as a crash.
    if proc is not None and proc.poll() is not None:
        return False, f"process exited (code {proc.returncode})"
    return False, f"timeout after {max_seconds}s"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def _missing_deps():
    import importlib.util
    return [m for m in REQUIRED if importlib.util.find_spec(m) is None]


def ensure_dependencies():
    print("[1/4] Checking dependencies...")
    missing = _missing_deps()
    if not missing:
        print("      Dependencies OK.")
        return
    print(f"      Missing: {', '.join(missing)} -- installing from requirements.txt ...")
    req = BASE_DIR / "requirements.txt"
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    rc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req)]
    ).returncode
    if rc != 0:
        raise RuntimeError(
            "pip install failed. Check your internet connection, then run manually:\n"
            f'    "{sys.executable}" -m pip install -r "{req}"'
        )
    still = _missing_deps()
    if still:
        raise RuntimeError(
            f"Required packages still not importable after install: {', '.join(still)}\n"
            f'Try:  "{sys.executable}" -m pip install -r "{req}"'
        )
    print("      Dependencies OK.")


# ---------------------------------------------------------------------------
# Port clearing
# ---------------------------------------------------------------------------

def _pids_on_port(port):
    """Best-effort list of PIDs listening on `port` (Windows netstat / POSIX)."""
    pids = set()
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["netstat", "-aon"], capture_output=True, text=True, timeout=10
            ).stdout
            needle = f":{port} "
            for line in out.splitlines():
                if needle in line and "LISTENING" in line.upper():
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pids.add(parts[-1])
        else:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            pids.update(p for p in out.split() if p.isdigit())
    except Exception:
        pass
    return pids


def free_port(port):
    pids = _pids_on_port(port)
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                               capture_output=True, timeout=10)
            else:
                os.kill(int(pid), 9)
        except Exception:
            pass
    return pids


def free_ports():
    print(f"[2/4] Clearing old processes on ports {API_PORT} and {UI_PORT} (if any)...")
    freed = free_port(API_PORT) | free_port(UI_PORT)
    if freed:
        print(f"      Freed PIDs: {', '.join(sorted(freed))}")
    print("      Done.")


# ---------------------------------------------------------------------------
# Subprocess startup
# ---------------------------------------------------------------------------

def _spawn(cmd):
    """Start a child process in its own group; stream its output to this console."""
    kw = {"cwd": str(BASE_DIR)}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    _CHILDREN.append(proc)
    return proc


def _terminate_children():
    for proc in _CHILDREN:
        if proc.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=10)
                else:
                    proc.terminate()
            except Exception:
                pass


def start_backend():
    print(f"[3/4] Starting backend API on http://{API_HOST}:{API_PORT} ...")
    proc = _spawn([
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", API_HOST, "--port", str(API_PORT), "--log-level", "info",
    ])
    print("      Waiting for the backend to become healthy...")
    ok, reason = wait_until_healthy(API_HEALTH_URL, proc=proc, max_seconds=30)
    if not ok:
        raise RuntimeError(
            f"Backend did not become healthy: {reason}.\n"
            "  The uvicorn output above shows the real error (missing package, "
            "port in use, import error, etc.)."
        )
    print("      Backend is healthy.")
    return proc


def start_ui():
    print(f"[4/4] Starting the Streamlit UI on http://localhost:{UI_PORT} ...")
    proc = _spawn([
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", str(UI_PORT), "--server.headless", "true",
    ])
    print("      Waiting for the UI to become available...")
    ok, reason = wait_until_healthy(UI_URL, proc=proc, max_seconds=60)
    if not ok:
        raise RuntimeError(
            f"Streamlit UI did not come up: {reason}.\n"
            "  The Streamlit output above shows the real error."
        )
    return proc


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run():
    atexit.register(_terminate_children)
    os.chdir(BASE_DIR)
    ensure_dependencies()
    free_ports()
    start_backend()
    start_ui()

    import webbrowser
    print(f"      UI is up. Opening your browser at http://localhost:{UI_PORT} ...")
    try:
        webbrowser.open(f"http://localhost:{UI_PORT}")
    except Exception:
        pass

    print("=" * 60)
    print(" Both servers are now running:")
    print(f"   * Backend API : http://{API_HOST}:{API_PORT}")
    print(f"   * Streamlit UI: http://localhost:{UI_PORT}")
    print("=" * 60)
    try:
        input("\nPress Enter (or close this window) to stop both servers...")
    except (EOFError, KeyboardInterrupt):
        pass


def main():
    try:
        run()
        return 0
    except Exception:
        print("\n" + "=" * 60)
        print(" [ERROR] The launcher hit a problem and could not continue.")
        print("=" * 60)
        traceback.print_exc()
        try:
            input("\nPress Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
