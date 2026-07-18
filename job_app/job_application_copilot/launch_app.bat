@echo off
setlocal enabledelayedexpansion

REM Anchor to this script's own folder, no matter where it is double-clicked from.
cd /d "%~dp0"

set "ENV_NAME=jobcopilot"
set "API_PORT=8000"
set "UI_PORT=8501"

echo ============================================================
echo  Job Application Copilot -- launcher
echo ============================================================
echo.

REM ============================================================
REM  STEP 0 -- Activate the "jobcopilot" Anaconda environment
REM ============================================================
echo [0/4] Activating conda environment "%ENV_NAME%"...

set "CONDA_ACT="

REM (a) If conda is already initialised in this shell, CONDA_EXE points at it.
if defined CONDA_EXE (
    for %%I in ("%CONDA_EXE%") do (
        if exist "%%~dpI..\Scripts\activate.bat" set "CONDA_ACT=%%~dpI..\Scripts\activate.bat"
    )
)

REM (b) Otherwise look for conda on PATH and derive activate.bat next to it.
if not defined CONDA_ACT (
    for /f "delims=" %%i in ('where conda 2^>nul') do (
        if not defined CONDA_ACT (
            if exist "%%~dpi..\Scripts\activate.bat" set "CONDA_ACT=%%~dpi..\Scripts\activate.bat"
        )
    )
)

REM (c) Fall back to the usual Anaconda / Miniconda install locations.
if not defined CONDA_ACT (
    for %%D in (
        "%USERPROFILE%\anaconda3"
        "%USERPROFILE%\miniconda3"
        "%USERPROFILE%\Anaconda3"
        "%USERPROFILE%\Miniconda3"
        "%LOCALAPPDATA%\anaconda3"
        "%LOCALAPPDATA%\miniconda3"
        "%LOCALAPPDATA%\Continuum\anaconda3"
        "%ProgramData%\anaconda3"
        "%ProgramData%\miniconda3"
        "%ProgramData%\Anaconda3"
        "%ProgramData%\Miniconda3"
        "C:\anaconda3"
        "C:\miniconda3"
    ) do (
        if not defined CONDA_ACT (
            if exist "%%~D\Scripts\activate.bat" set "CONDA_ACT=%%~D\Scripts\activate.bat"
        )
    )
)

if not defined CONDA_ACT (
    echo.
    echo [ERROR] Could not find Anaconda / Miniconda on this machine.
    echo.
    echo   Install Miniconda from:
    echo       https://docs.conda.io/en/latest/miniconda.html
    echo.
    echo   If conda IS installed but not found, open the "Anaconda Prompt",
    echo   run:   conda init cmd.exe
    echo   then close and re-run this launcher.
    echo.
    pause
    exit /b 1
)

echo       Found conda: !CONDA_ACT!

REM Activate the named environment. The classic "activate.bat <env>" form works
REM from a plain .bat and sets CONDA_DEFAULT_ENV when it succeeds.
call "!CONDA_ACT!" %ENV_NAME%

if not "!CONDA_DEFAULT_ENV!"=="%ENV_NAME%" (
    echo.
    echo [ERROR] Could not activate the conda environment "%ENV_NAME%".
    echo.
    echo   Create it once with these two commands in an Anaconda Prompt:
    echo       conda create -n %ENV_NAME% python=3.12 -y
    echo       conda activate %ENV_NAME%
    echo       pip install -r requirements.txt
    echo.
    echo   Then double-click this launcher again.
    echo.
    pause
    exit /b 1
)

REM Resolve the environment's python.exe (full path, for clear messages).
set "PYTHON_EXE=python"
for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%i"
echo       Active env: !CONDA_DEFAULT_ENV!
echo       Python:     !PYTHON_EXE!
echo.

REM ============================================================
REM  STEP 1 -- Verify / install dependencies
REM ============================================================
echo [1/4] Checking dependencies...
python -c "import streamlit, fastapi, uvicorn" >nul 2>&1
if !errorlevel! neq 0 (
    echo       Some packages are missing -- installing from requirements.txt ...
    python -m pip install -q --upgrade pip
    python -m pip install -r requirements.txt
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] pip install failed.
        echo   Check your internet connection, then run manually:
        echo       python -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    REM Re-check after install.
    python -c "import streamlit, fastapi, uvicorn" >nul 2>&1
    if !errorlevel! neq 0 (
        echo.
        echo [ERROR] Required packages still not importable after install.
        echo   Try:  python -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)
echo       Dependencies OK.
echo.

REM ============================================================
REM  STEP 2 -- Free ports 8000 (backend) and 8501 (UI)
REM ============================================================
echo [2/4] Clearing old processes on ports %API_PORT% and %UI_PORT% (if any)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%API_PORT% "') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%UI_PORT% "')  do taskkill /PID %%a /F >nul 2>&1
echo       Done.
echo.

REM ============================================================
REM  STEP 3 -- Start the FastAPI backend and WAIT until healthy
REM ============================================================
echo [3/4] Starting backend API on http://127.0.0.1:%API_PORT% ...
REM Launch uvicorn in its own titled window (cmd /k keeps it open so any
REM traceback stays visible instead of the window flashing and closing).
start "JobCopilot Backend (port %API_PORT%)" cmd /k ""!PYTHON_EXE!" -m uvicorn backend.main:app --host 127.0.0.1 --port %API_PORT%"

echo       Waiting for the backend to become healthy...
REM Poll /health for up to ~30s using PowerShell (always present on Windows).
powershell -NoProfile -Command "$u='http://127.0.0.1:%API_PORT%/health'; for($i=0;$i -lt 30;$i++){ try{ if((Invoke-WebRequest -UseBasicParsing $u -TimeoutSec 2).StatusCode -eq 200){ exit 0 } }catch{}; Start-Sleep -Seconds 1 }; exit 1"
if !errorlevel! neq 0 (
    echo.
    echo [ERROR] The backend did not report healthy within 30 seconds.
    echo   Look at the "JobCopilot Backend" window that just opened -- the real
    echo   error (missing package, port in use, import error) is printed there.
    echo   A copy is also saved in:  backend_startup.log
    echo.
    echo   Common fixes:
    echo     * Port %API_PORT% already in use  -- close the other program / reboot.
    echo     * ModuleNotFoundError             -- python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo       Backend is healthy.
echo.

REM ============================================================
REM  STEP 4 -- Start the Streamlit UI (opens the browser itself)
REM ============================================================
echo [4/4] Starting the Streamlit UI on http://localhost:%UI_PORT% ...
echo       Your browser should open automatically. If not, open that URL.
echo.
REM headless=false lets Streamlit open the default browser once it is ready
REM (no premature/blank tab, no double-open).
python -m streamlit run app.py --server.port %UI_PORT% --server.headless false

echo.
echo Streamlit exited. The backend window can be closed separately.
pause
