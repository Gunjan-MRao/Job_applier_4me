@echo off
setlocal enabledelayedexpansion

REM ── Auto-detect the folder this .bat lives in ────────────────────────────
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "BACKEND_PORT=8000"
set "STREAMLIT_PORT=8501"
set "JOBSPY_PORT=8010"

REM ── Auto-detect Python from the active conda/venv environment ────────────
REM (No more hardcoded path — works on any machine with a conda env active)
for /f "delims=" %%i in ('where python 2^>nul') do (
    set "PYTHON=%%i"
    goto :found_python
)
:not_found
echo.
echo ERROR: Python not found in PATH.
echo Activate your conda environment first, e.g.:
echo   conda activate jobcopilot
echo Then re-run this script.
echo.
pause
exit /b 1

:found_python
echo.
echo ==========================================
echo  Job Application Copilot  ^|  One-Click Start
echo ==========================================
echo  Project  : %PROJECT_DIR%
echo  Python   : %PYTHON%
echo  Backend  : http://127.0.0.1:%BACKEND_PORT%
echo  Frontend : http://localhost:%STREAMLIT_PORT%
echo ==========================================
echo.

if not exist "%PROJECT_DIR%\app.py" (
    echo ERROR: app.py not found in %PROJECT_DIR%
    pause
    exit /b 1
)

REM ── Install / update dependencies from root requirements.txt ─────────────
set "ROOT_REQS=%PROJECT_DIR%\..\..\requirements.txt"
if not exist "%ROOT_REQS%" set "ROOT_REQS=%PROJECT_DIR%\requirements.txt"

if exist "%ROOT_REQS%" (
    echo [0/3] Installing dependencies from requirements.txt ...
    "%PYTHON%" -m pip install -r "%ROOT_REQS%" --quiet --disable-pip-version-check
    if errorlevel 1 (
        echo WARNING: pip install reported errors — continuing anyway.
        echo          Check the output above if something fails to import.
    ) else (
        echo         Dependencies OK.
    )
    echo.
) else (
    echo WARNING: requirements.txt not found at %ROOT_REQS% — skipping install.
    echo.
)

REM ── Kill anything already on these ports ─────────────────────────────────
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%BACKEND_PORT% "') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%STREAMLIT_PORT% "') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%JOBSPY_PORT% "') do taskkill /F /PID %%a >nul 2>&1

REM ── 1. Start FastAPI backend ──────────────────────────────────────────────
echo [1/3] Starting FastAPI backend on port %BACKEND_PORT% ...
start "Backend - FastAPI" cmd /k "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

REM Wait for backend to initialise
timeout /t 4 /nobreak >nul

REM ── Health-check the backend ──────────────────────────────────────────────
"%PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%BACKEND_PORT%/health')" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Backend may not have started yet — check the Backend window.
) else (
    echo         Backend is healthy.
)
echo.

REM ── 2. Start JobSpy sidecar (optional) ───────────────────────────────────
set "JOBSPY_SCRIPT=%PROJECT_DIR%\..\jobspy_service\jobspy_api.py"
if exist "%JOBSPY_SCRIPT%" (
    echo [2/3] Starting JobSpy sidecar on port %JOBSPY_PORT% ...
    start "Sidecar - JobSpy" cmd /k "cd /d "%PROJECT_DIR%\..\jobspy_service" && "%PYTHON%" -m uvicorn jobspy_api:app --host 127.0.0.1 --port %JOBSPY_PORT%"
    timeout /t 2 /nobreak >nul
) else (
    echo [2/3] JobSpy sidecar not found — skipping ^(app uses direct jobspy calls^).
)
echo.

REM ── 3. Start Streamlit frontend ───────────────────────────────────────────
echo [3/3] Starting Streamlit frontend on port %STREAMLIT_PORT% ...
start "Frontend - Streamlit" cmd /k "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m streamlit run app.py --server.port %STREAMLIT_PORT% --server.headless true --browser.serverAddress localhost"

REM ── Open browser once both services are up ────────────────────────────────
timeout /t 5 /nobreak >nul
start "" http://localhost:%STREAMLIT_PORT%

echo.
echo ==========================================
echo  All services started.
echo  Backend  : http://127.0.0.1:%BACKEND_PORT%/docs
echo  Frontend : http://localhost:%STREAMLIT_PORT%
echo  Close the terminal windows to stop each service.
echo ==========================================
echo.
