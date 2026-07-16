@echo off
setlocal

REM ── Auto-detect the folder this .bat lives in ────────────────────────────
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "BACKEND_PORT=8000"
set "STREAMLIT_PORT=8501"

REM ── Exact Python path for jobcopilot conda env ───────────────────────────
set "PYTHON=C:\Users\gunja\anaconda3\New folder\envs\jobcopilot\python.exe"

if not exist "%PYTHON%" (
    echo.
    echo ERROR: Python not found at:
    echo %PYTHON%
    echo.
    echo Open Anaconda Prompt and run:  where python
    echo Then update the PYTHON line in this .bat file.
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Job Application Copilot  ^|  One-Click Start
echo ==========================================
echo  Project  : %PROJECT_DIR%
echo  Backend  : http://127.0.0.1:%BACKEND_PORT%
echo  Frontend : http://localhost:%STREAMLIT_PORT%
echo ==========================================
echo.

if not exist "%PROJECT_DIR%\app.py" (
    echo ERROR: app.py not found in %PROJECT_DIR%
    pause
    exit /b 1
)

REM ── Kill anything already on these ports ─────────────────────────────────
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%BACKEND_PORT% "') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%STREAMLIT_PORT% "') do taskkill /F /PID %%a >nul 2>&1

REM ── 1. Start FastAPI backend ───────────────────────────────────────────────
echo [1/2] Starting FastAPI backend on port %BACKEND_PORT%...
start "Backend - FastAPI" cmd /k "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

REM Wait for backend to initialise before starting frontend
timeout /t 4 /nobreak >nul

REM ── 2. Start Streamlit frontend (browser.serverAddress prevents double tab) ──
echo [2/2] Starting Streamlit frontend on port %STREAMLIT_PORT%...
start "Frontend - Streamlit" cmd /k "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m streamlit run app.py --server.port %STREAMLIT_PORT% --server.headless true --browser.serverAddress localhost"

REM ── Open browser exactly once ──────────────────────────────────────────────
timeout /t 5 /nobreak >nul
start "" http://localhost:%STREAMLIT_PORT%

echo.
echo Both services are running.
echo Close the two terminal windows to stop them.
echo.
