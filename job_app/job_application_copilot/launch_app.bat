@echo off
setlocal

REM ── Auto-detect the folder this .bat lives in ────────────────────────────
set "PROJECT_DIR=%~dp0"
REM Remove trailing backslash
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

REM ── Ports ────────────────────────────────────────────────────────────────
set "BACKEND_PORT=8000"
set "STREAMLIT_PORT=8501"

REM ── Find Python (tries conda base, then plain PATH) ──────────────────────
set "PYTHON="
for %%P in (
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\Anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "%LOCALAPPDATA%\anaconda3\python.exe"
    "%USERPROFILE%\anaconda3\Anaconda\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
    "C:\ProgramData\Anaconda3\python.exe"
) do (
    if exist %%P (
        set "PYTHON=%%~P"
        goto :found_python
    )
)
REM Last resort: whatever python is on PATH
where python >nul 2>&1 && set "PYTHON=python"
:found_python

if "%PYTHON%"=="" (
    echo ERROR: Could not find Python / Anaconda.
    echo Please install Anaconda or add Python to PATH.
    pause
    exit /b 1
)

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

REM ── Kill anything already on these ports ─────────────────────────────────
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%BACKEND_PORT% "') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%STREAMLIT_PORT% "') do taskkill /F /PID %%a >nul 2>&1

REM ── 1. Start FastAPI backend in its own window ───────────────────────────
echo [1/2] Starting FastAPI backend on port %BACKEND_PORT%...
start "Backend - FastAPI" cmd /k ^
    "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

REM ── Wait 3 seconds for backend to be ready ───────────────────────────────
timeout /t 3 /nobreak >nul

REM ── 2. Start Streamlit frontend in its own window ────────────────────────
echo [2/2] Starting Streamlit frontend on port %STREAMLIT_PORT%...
start "Frontend - Streamlit" cmd /k ^
    "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m streamlit run app.py --server.port %STREAMLIT_PORT% --server.headless false"

REM ── Open browser after 5 seconds ─────────────────────────────────────────
timeout /t 5 /nobreak >nul
start http://localhost:%STREAMLIT_PORT%

echo.
echo Both services are running.
echo Close the two terminal windows to stop them.
echo.
pause
