@echo off
setlocal

cd /d "%~dp0"

echo ============================================================
echo  Job Application Copilot — launcher
echo ============================================================
echo.

REM ── Locate Python ────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found on PATH. Please install Python 3.10+.
    pause
    exit /b 1
)

echo [1/3] Installing / upgrading dependencies...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo       Done.
echo.

REM ── Kill any old Streamlit on port 8501 ─────────────────────
echo [2/3] Clearing old Streamlit process on port 8501 (if any)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo       Done.
echo.

echo [3/3] Starting Streamlit...
echo       URL: http://localhost:8501
echo.

REM Open browser automatically
start http://localhost:8501

REM Launch Streamlit (blocking)
python -m streamlit run app.py --server.port 8501 --server.headless false

echo.
echo Streamlit exited.
pause
