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
REM  STEP 1-4 -- Hand off to the Python launcher
REM ------------------------------------------------------------
REM  Everything after conda activation (dependency check, port clearing, starting
REM  the backend + Streamlit, health-polling, and opening the browser) is done by
REM  launch.py. Python has far more reliable subprocess/polling/error-handling
REM  than Windows batch -- and, crucially, any failure prints a real traceback
REM  instead of the window silently vanishing (the exact regression we hit when
REM  this orchestration lived in batch across several rounds of shell-poll bugs).
REM  We `call` the interpreter (not `start`) so its output stays in THIS window,
REM  and `pause` afterwards no matter what so the window can never close before
REM  you have read whatever it printed (including any Python traceback).
REM ============================================================
call "!PYTHON_EXE!" "%~dp0launch.py"

echo.
pause
exit /b %errorlevel%

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
