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
REM  MANUAL OVERRIDE (last-resort fallback)
REM ------------------------------------------------------------
REM  If auto-detection below ever fails, open your "Anaconda Prompt",
REM  run:   conda info --base
REM  copy the path it prints, and set it on the line below, e.g.
REM      set "CONDA_BASE=C:\Users\gunja\anaconda3\New folder"
REM  (Spaces in the path are fine -- keep the quotes.)
REM  The default below preserves a CONDA_BASE user env var if you set one
REM  (see OPTION 2 in the error message); replace it with a literal path to
REM  hard-code your install here instead.
REM ============================================================
set "CONDA_BASE=%CONDA_BASE%"

REM ============================================================
REM  STEP 0 -- Locate + activate the "jobcopilot" Anaconda environment
REM ============================================================
echo [0/4] Locating conda...

REM (0) Honour a manually-set CONDA_BASE (from the block above or a user env var).
if defined CONDA_BASE (
    if not exist "%CONDA_BASE%\Scripts\activate.bat" (
        echo       [warn] CONDA_BASE is set but "%CONDA_BASE%\Scripts\activate.bat" was not found -- ignoring it.
        set "CONDA_BASE="
    )
)

REM (a) If conda is already initialised in this shell, CONDA_EXE points at it.
REM     CONDA_EXE is like ...\Scripts\conda.exe or ...\condabin\conda.bat;
REM     the install base is its grandparent folder.
if not defined CONDA_BASE if defined CONDA_EXE (
    for %%I in ("%CONDA_EXE%") do (
        for %%J in ("%%~dpI..") do (
            if exist "%%~fJ\Scripts\activate.bat" set "CONDA_BASE=%%~fJ"
        )
    )
)

REM (b) conda on PATH -> derive the base from its location.
if not defined CONDA_BASE (
    for /f "delims=" %%i in ('where conda 2^>nul') do (
        if not defined CONDA_BASE (
            for %%J in ("%%~dpi..") do (
                if exist "%%~fJ\Scripts\activate.bat" set "CONDA_BASE=%%~fJ"
            )
        )
    )
)

REM (c) REAL SEARCH: scan common roots (and up to 2 levels of sub-folders) for a
REM     directory that actually contains condabin\conda.bat + Scripts\activate.bat.
REM     This finds installs regardless of sub-folder naming, e.g. a base literally
REM     named "...\anaconda3\New folder", including paths that contain spaces.
if not defined CONDA_BASE call :scan_root "%USERPROFILE%"
if not defined CONDA_BASE call :scan_root "%LOCALAPPDATA%"
if not defined CONDA_BASE call :scan_root "%LOCALAPPDATA%\Continuum"
if not defined CONDA_BASE call :scan_root "%ProgramData%"
REM     Shallow well-known drive-root installs (no deep C:\ walk, for speed).
if not defined CONDA_BASE (
    for %%D in ("C:\anaconda3" "C:\miniconda3" "C:\ProgramData\Anaconda3" "C:\ProgramData\Miniconda3") do (
        if not defined CONDA_BASE call :check_dir "%%~D"
    )
)

REM (d) Registry fallback: Anaconda/Miniconda often register their InstallPath.
if not defined CONDA_BASE call :scan_registry "HKCU\Software\Python\ContinuumAnalytics"
if not defined CONDA_BASE call :scan_registry "HKLM\Software\Python\ContinuumAnalytics"
if not defined CONDA_BASE call :scan_registry "HKCU\Software\Python\PythonCore"

if not defined CONDA_BASE (
    echo.
    echo [ERROR] Could not automatically locate your Anaconda / Miniconda install.
    echo.
    echo   You clearly HAVE conda, so this is just a detection miss. Fix it in
    echo   under a minute -- do EITHER of these:
    echo.
    echo   OPTION 1 ^(easiest^): tell this launcher where conda is.
    echo     1. Open your "Anaconda Prompt".
    echo     2. Run:   conda info --base
    echo     3. Copy the path it prints ^(e.g. C:\Users\gunja\anaconda3\New folder^).
    echo     4. Open launch_app.bat in Notepad, find the line near the top that
    echo        begins with:   set "CONDA_BASE=
    echo        and set it to your path, keeping the quotes, e.g.
    echo          set "CONDA_BASE=C:\Users\gunja\anaconda3\New folder"
    echo     5. Save and double-click launch_app.bat again.
    echo.
    echo   OPTION 2: set a permanent user environment variable.
    echo     Run this once in an Anaconda Prompt ^(use YOUR path from step 2^):
    echo        setx CONDA_BASE "C:\Users\gunja\anaconda3\New folder"
    echo     Then open a NEW window and re-run launch_app.bat.
    echo.
    pause
    exit /b 1
)

set "CONDA_ACT=%CONDA_BASE%\Scripts\activate.bat"
echo       Found conda base: !CONDA_BASE!

REM Activate the named environment. The classic "activate.bat <env>" form works
REM from a plain .bat and sets CONDA_DEFAULT_ENV when it succeeds. Quotes matter
REM because the path may contain spaces.
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
REM Poll /health until it returns 200 (see :poll_url -- uses curl.exe, which is
REM built into Windows 10 1803+/11, and falls back to PowerShell on older boxes).
call :poll_url "http://127.0.0.1:%API_PORT%/health" 30
if not defined POLL_OK (
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
REM  STEP 4 -- Start the Streamlit UI, then open the browser ourselves
REM ============================================================
echo [4/4] Starting the Streamlit UI on http://localhost:%UI_PORT% ...
REM IMPORTANT: run Streamlit with --server.headless true.
REM   With headless=false, a FIRST run of Streamlit prints an interactive
REM   "Welcome to Streamlit!  Email:" prompt and then BLOCKS waiting for you to
REM   type something on the keyboard. From a double-clicked .bat that looks like
REM   nothing happens -- no browser opens and no app appears -- which is exactly
REM   the symptom we hit. headless=true skips that prompt and starts immediately.
REM   Because headless mode does not auto-open a browser, we open it ourselves
REM   below once the UI is confirmed up, so a broken browser association can never
REM   make it look like the UI failed to launch.
REM   Use the resolved full python path (same one the backend uses) and give the
REM   UI its own window so any startup error stays visible instead of vanishing.
start "JobCopilot UI (port %UI_PORT%)" cmd /k ""!PYTHON_EXE!" -m streamlit run app.py --server.port %UI_PORT% --server.headless true"

echo       Waiting for the UI to become available...
REM Poll the UI port until 200, up to ~60s (first run may compile/import slowly).
call :poll_url "http://127.0.0.1:%UI_PORT%/" 60
if not defined POLL_OK (
    echo.
    echo [ERROR] The Streamlit UI did not come up within 60 seconds.
    echo   Look at the "JobCopilot UI" window that just opened -- the real error
    echo   ^(missing package, port in use, import error^) is printed there.
    echo.
    pause
    exit /b 1
)

echo       UI is up. Opening your browser at http://localhost:%UI_PORT% ...
start "" "http://localhost:%UI_PORT%"
echo.
echo ============================================================
echo  Both servers are now running, each in its own window:
echo    * Backend API : http://127.0.0.1:%API_PORT%
echo    * Streamlit UI: http://localhost:%UI_PORT%
echo  Close those two windows ^(or press Ctrl+C in them^) to stop the app.
echo ============================================================
pause
exit /b 0

REM ============================================================
REM  Subroutines
REM ============================================================

REM --- :scan_root <root> ------------------------------------------------------
REM  Checks <root> and every sub-folder up to 2 levels deep for a conda base.
REM  Sets CONDA_BASE on the first match. Handles folder names with spaces.
:scan_root
set "_ROOT=%~1"
if "%_ROOT%"=="" goto :eof
if not exist "%_ROOT%\" goto :eof
call :check_dir "%_ROOT%"
if defined CONDA_BASE goto :eof
for /d %%A in ("%_ROOT%\*") do (
    if not defined CONDA_BASE call :check_dir "%%~fA"
    if not defined CONDA_BASE (
        for /d %%B in ("%%~fA\*") do (
            if not defined CONDA_BASE call :check_dir "%%~fB"
        )
    )
)
goto :eof

REM --- :check_dir <dir> -------------------------------------------------------
REM  If <dir> looks like a conda base (has condabin\conda.bat OR
REM  Scripts\activate.bat), record it in CONDA_BASE.
:check_dir
if defined CONDA_BASE goto :eof
set "_D=%~1"
if exist "%_D%\condabin\conda.bat" if exist "%_D%\Scripts\activate.bat" (
    set "CONDA_BASE=%_D%"
    goto :eof
)
REM Some minimal installs ship activate.bat without condabin -- accept those too.
if exist "%_D%\Scripts\activate.bat" if exist "%_D%\python.exe" set "CONDA_BASE=%_D%"
goto :eof

REM --- :scan_registry <key> ---------------------------------------------------
REM  Walks an Anaconda/Python registry key subtree and accepts the first REG_SZ
REM  value whose data is a valid conda base (i.e. has Scripts\activate.bat).
REM  This catches the InstallPath key's default value even when the path has
REM  spaces; non-base values (e.g. ExecutablePath -> python.exe) fail the check.
:scan_registry
for /f "tokens=2,*" %%A in ('reg query "%~1" /s 2^>nul ^| findstr /i "REG_SZ"') do (
    if not defined CONDA_BASE (
        if exist "%%~B\Scripts\activate.bat" set "CONDA_BASE=%%~B"
    )
)
goto :eof

REM --- :poll_url <url> <max_seconds> ------------------------------------------
REM  Polls <url> once per second until it returns HTTP 200 or <max_seconds>
REM  attempts are exhausted. Sets POLL_OK=1 on success; leaves it undefined on
REM  timeout. The caller checks "if not defined POLL_OK".
REM
REM  Primary path: curl.exe (present on Windows 10 1803+ and all Windows 11 at
REM  %SystemRoot%\System32\curl.exe). A plain HTTP GET + status check with hard
REM  --connect-timeout/--max-time is simple and predictable -- no PowerShell
REM  startup cost, module autoload, execution-policy or IE-engine/proxy quirks
REM  that were making the old "powershell Invoke-WebRequest" one-liner hang after
REM  a successful 200 on some real Windows machines.
REM
REM  Fallback: if curl.exe cannot be found at all (very old Windows), use the
REM  original PowerShell one-liner so nothing regresses on edge-case boxes.
:poll_url
set "POLL_OK="
set "_URL=%~1"
set "_MAX=%~2"
set "_CURL="
if exist "%SystemRoot%\System32\curl.exe" set "_CURL=%SystemRoot%\System32\curl.exe"
if not defined _CURL for %%X in (curl.exe) do if not defined _CURL if not "%%~$PATH:X"=="" set "_CURL=%%~$PATH:X"
if defined _CURL (
    for /l %%i in (1,1,%_MAX%) do (
        if not defined POLL_OK (
            set "CODE=000"
            for /f "usebackq delims=" %%C in (`"!_CURL!" -s -o nul -w "%%{http_code}" --connect-timeout 2 --max-time 5 "%_URL%" 2^>nul`) do set "CODE=%%C"
            if "!CODE!"=="200" (
                set "POLL_OK=1"
            ) else (
                timeout /t 1 /nobreak >nul 2>&1
            )
        )
    )
    goto :eof
)
REM Fallback: PowerShell (only reached when curl.exe is genuinely absent).
powershell -NoProfile -Command "$u='%_URL%'; for($i=0;$i -lt %_MAX%;$i++){ try{ if((Invoke-WebRequest -UseBasicParsing $u -TimeoutSec 2).StatusCode -eq 200){ exit 0 } }catch{}; Start-Sleep -Seconds 1 }; exit 1"
if !errorlevel! equ 0 set "POLL_OK=1"
goto :eof
