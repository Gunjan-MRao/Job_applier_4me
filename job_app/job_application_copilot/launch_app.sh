#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Job Application Copilot -- launcher (macOS / Linux / Git-Bash fallback)
#
# This mirrors launch_app.bat step-for-step for users who are NOT on plain
# Windows cmd.exe (macOS, Linux, or Git-Bash on Windows). Same sequence:
#   0) activate the "jobcopilot" conda env (fall back to python on PATH)
#   1) verify / install dependencies
#   2) free ports 8000 / 8501
#   3) start the FastAPI backend and WAIT until /health is 200
#   4) start Streamlit and open the browser
# ---------------------------------------------------------------------------
set -u

ENV_NAME="jobcopilot"
API_PORT=8000
UI_PORT=8501

# Anchor to this script's own directory (equivalent of %~dp0).
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" || exit 1

echo "============================================================"
echo " Job Application Copilot -- launcher"
echo "============================================================"

# --- STEP 0: activate the jobcopilot conda env (graceful fallback) ----------
echo "[0/4] Activating conda environment '$ENV_NAME'..."
PY="python"
if command -v conda >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"
    if conda activate "$ENV_NAME" 2>/dev/null; then
        PY="python"
        echo "      Active env: $ENV_NAME"
    else
        echo "[ERROR] conda env '$ENV_NAME' not found."
        echo "  Create it once with:"
        echo "      conda create -n $ENV_NAME python=3.12 -y"
        echo "      conda activate $ENV_NAME"
        echo "      pip install -r requirements.txt"
        exit 1
    fi
else
    # No conda: use python3/python on PATH so the app still runs.
    command -v python  >/dev/null 2>&1 || PY="python3"
    command -v "$PY"   >/dev/null 2>&1 || { echo "[ERROR] No python found on PATH."; exit 1; }
    echo "      conda not found -- using '$PY' on PATH."
fi
echo "      Python: $("$PY" -c 'import sys;print(sys.executable)')"

# --- STEP 1: verify / install dependencies ---------------------------------
echo "[1/4] Checking dependencies..."
if ! "$PY" -c "import streamlit, fastapi, uvicorn" >/dev/null 2>&1; then
    echo "      Installing from requirements.txt ..."
    "$PY" -m pip install -q --upgrade pip
    if ! "$PY" -m pip install -r requirements.txt; then
        echo "[ERROR] pip install failed. Run: $PY -m pip install -r requirements.txt"
        exit 1
    fi
fi
echo "      Dependencies OK."

# --- STEP 2: free ports -----------------------------------------------------
echo "[2/4] Clearing old processes on ports $API_PORT and $UI_PORT (if any)..."
for p in "$API_PORT" "$UI_PORT"; do
    if command -v fuser >/dev/null 2>&1; then fuser -k "${p}/tcp" >/dev/null 2>&1 || true; fi
done
sleep 1

# --- STEP 3: start backend and WAIT until healthy --------------------------
echo "[3/4] Starting backend API on http://127.0.0.1:$API_PORT ..."
"$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port "$API_PORT" \
    > backend_startup.log 2>&1 &
BACKEND_PID=$!

echo "      Waiting for the backend to become healthy..."
healthy=0
for _ in $(seq 1 30); do
    if curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/health" 2>/dev/null; then
        healthy=1; break
    fi
    # If the backend process already died, stop waiting.
    kill -0 "$BACKEND_PID" 2>/dev/null || break
    sleep 1
done
if [ "$healthy" -ne 1 ]; then
    echo "[ERROR] Backend did not report healthy within 30s. Last log lines:"
    tail -n 20 backend_startup.log 2>/dev/null
    kill "$BACKEND_PID" 2>/dev/null || true
    exit 1
fi
echo "      Backend is healthy (PID $BACKEND_PID)."

# --- STEP 4: start Streamlit + open browser --------------------------------
echo "[4/4] Starting the Streamlit UI on http://localhost:$UI_PORT ..."
( command -v xdg-open >/dev/null 2>&1 && xdg-open "http://localhost:$UI_PORT" >/dev/null 2>&1 & ) || true
( command -v open     >/dev/null 2>&1 && open     "http://localhost:$UI_PORT" >/dev/null 2>&1 & ) || true
"$PY" -m streamlit run app.py --server.port "$UI_PORT" --server.headless true

echo "Streamlit exited. Stopping backend..."
kill "$BACKEND_PID" 2>/dev/null || true
