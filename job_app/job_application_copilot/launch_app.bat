@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  Job Application Copilot  -  One-Click Launcher
REM  Double-click this file; no pre-activated environment needed.
REM ============================================================

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "CONDA_ENV_NAME=jobcopilot"
set "BACKEND_PORT=8000"
set "STREAMLIT_PORT=8501"
set "JOBSPY_PORT=8010"

echo.
echo ==========================================
echo  Job Application Copilot  ^|  One-Click Start
echo ==========================================
echo.

REM ── STEP 1: Try to find Python already in PATH ───────────────────────────
for /f "delims=" %%i in ('where python 2^>nul') do (
    set "PYTHON=%%i"
    goto :verify_python
)

REM ── STEP 2: Try activating via conda.bat (works for Anaconda installs) ───
echo Python not found in PATH. Trying to activate conda env '%CONDA_ENV_NAME%' ...

REM Look for conda.bat / activate.bat in common Anaconda locations
for %%R in (
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\Anaconda3"
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\Miniconda3"
    "C:\ProgramData\anaconda3"
    "C:\ProgramData\Anaconda3"
    "C:\ProgramData\miniconda3"
    "C:\ProgramData\Miniconda3"
    "%USERPROFILE%\anaconda3\New folder"
    "C:\tools\anaconda3"
    "C:\tools\miniconda3"
) do (
    if exist "%%~R\Scripts\activate.bat" (
        echo Found conda at %%~R
        call "%%~R\Scripts\activate.bat" "%%~R\envs\%CONDA_ENV_NAME%" >nul 2>&1
        for /f "delims=" %%i in ('where python 2^>nul') do (
            set "PYTHON=%%i"
            goto :verify_python
        )
    )
)

REM ── STEP 3: Try %CONDA_EXE% if conda is registered in the registry ───────
if defined CONDA_EXE (
    echo Trying CONDA_EXE: %CONDA_EXE% ...
    "%CONDA_EXE%" activate %CONDA_ENV_NAME% >nul 2>&1
    for /f "delims=" %%i in ('where python 2^>nul') do (
        set "PYTHON=%%i"
        goto :verify_python
    )
)

REM ── STEP 4: Known path fallback (Gunjan's machine) ───────────────────────
set "FALLBACK_PYTHON=C:\Users\gunja\anaconda3\New folder\envs\jobcopilot\python.exe"
if exist "%FALLBACK_PYTHON%" (
    echo Using known fallback Python path.
    set "PYTHON=%FALLBACK_PYTHON%"
    goto :verify_python
)

REM ── All strategies exhausted ──────────────────────────────────────────────
echo.
echo ERROR: Could not find Python for the '%CONDA_ENV_NAME%' environment.
echo.
echo To fix this, open Anaconda Prompt / Terminal and run:
echo   conda activate %CONDA_ENV_NAME%
echo Then double-click launch_app.bat again.
echo.
echo If your environment has a different name, edit CONDA_ENV_NAME at the
echo top of this .bat file.
echo.
pause
exit /b 1

REM ── Verify the Python we found is actually usable ────────────────────────
:verify_python
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python found at %PYTHON% but it failed to run.
    pause
    exit /b 1
)

echo  Python   : %PYTHON%
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

REM ── Install / update dependencies ────────────────────────────────────────
set "ROOT_REQS=%PROJECT_DIR%\..\..\requirements.txt"
if not exist "%ROOT_REQS%" set "ROOT_REQS=%PROJECT_DIR%\requirements.txt"

if exist "%ROOT_REQS%" (
    echo [0/3] Installing / verifying dependencies ...
    "%PYTHON%" -m pip install -r "%ROOT_REQS%" --quiet --disable-pip-version-check
    if errorlevel 1 (
        echo WARNING: pip install reported errors - continuing anyway.
    ) else (
        echo         Dependencies OK.
    )
    echo.
) else (
    echo WARNING: requirements.txt not found - skipping install.
    echo.
)

REM ── Kill anything already on these ports ─────────────────────────────────
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%BACKEND_PORT% "') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%STREAMLIT_PORT% "') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%JOBSPY_PORT% "') do taskkill /F /PID %%a >nul 2>&1

REM ── 1. Start FastAPI backend ──────────────────────────────────────────────
echo [1/3] Starting FastAPI backend on port %BACKEND_PORT% ...
start "Backend - FastAPI" cmd /k "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"
timeout /t 4 /nobreak >nul

REM Health-check
"%PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%BACKEND_PORT%/health')" >nul 2>&1
if errorlevel 1 (
    echo WARNING: Backend health check failed - check the Backend window.
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
    echo [2/3] JobSpy sidecar not present - skipping ^(app calls jobspy directly^).
)
echo.

REM ── 3. Start Streamlit frontend ───────────────────────────────────────────
echo [3/3] Starting Streamlit frontend on port %STREAMLIT_PORT% ...
start "Frontend - Streamlit" cmd /k "cd /d "%PROJECT_DIR%" && "%PYTHON%" -m streamlit run app.py --server.port %STREAMLIT_PORT% --server.headless true --browser.serverAddress localhost"

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
