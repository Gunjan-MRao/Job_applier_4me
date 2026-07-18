@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ============================================================
echo  Job Application Copilot -- launcher
echo ============================================================
echo.

REM ============================================================
REM  STEP 0 -- Find Python, trying every common Windows location
REM ============================================================
set PYTHON_EXE=

REM Try 1: py launcher (most reliable on Windows)
where py >nul 2>&1
if %errorlevel% equ 0 (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON_EXE=%%i
)

REM Try 2: python on PATH
if "!PYTHON_EXE!"=="" (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('where python 2^>nul') do (
            if "!PYTHON_EXE!"=="" set PYTHON_EXE=%%i
        )
    )
)

REM Try 3: python3 on PATH
if "!PYTHON_EXE!"=="" (
    where python3 >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('where python3 2^>nul') do (
            if "!PYTHON_EXE!"=="" set PYTHON_EXE=%%i
        )
    )
)

REM Try 4: Windows Store / AppData installs (Python 3.13 down to 3.9)
if "!PYTHON_EXE!"=="" (
    for %%V in (3.13 3.12 3.11 3.10 3.9) do (
        if "!PYTHON_EXE!"=="" (
            if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
                set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe
            )
        )
        if "!PYTHON_EXE!"=="" (
            REM strip the dot to get folder name like Python313
            set VV=%%V
            set VV=!VV:.=!
            if exist "%LOCALAPPDATA%\Programs\Python\Python!VV!\python.exe" (
                set PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python!VV!\python.exe
            )
        )
    )
)

REM Try 5: Program Files installs
if "!PYTHON_EXE!"=="" (
    for %%V in (313 312 311 310 39) do (
        if "!PYTHON_EXE!"=="" (
            if exist "%ProgramFiles%\Python%%V\python.exe" (
                set PYTHON_EXE=%ProgramFiles%\Python%%V\python.exe
            )
        )
    )
)

REM Try 6: Anaconda / Miniconda (user)
if "!PYTHON_EXE!"=="" (
    for %%D in (anaconda3 miniconda3 anaconda miniconda) do (
        if "!PYTHON_EXE!"=="" (
            if exist "%USERPROFILE%\%%D\python.exe" (
                set PYTHON_EXE=%USERPROFILE%\%%D\python.exe
            )
        )
    )
)

REM Try 7: Anaconda / Miniconda (system)
if "!PYTHON_EXE!"=="" (
    for %%D in (anaconda3 miniconda3) do (
        if "!PYTHON_EXE!"=="" (
            if exist "C:\%%D\python.exe" set PYTHON_EXE=C:\%%D\python.exe
            if exist "%ProgramData%\%%D\python.exe" set PYTHON_EXE=%ProgramData%\%%D\python.exe
        )
    )
)

if "!PYTHON_EXE!"=="" (
    echo.
    echo [ERROR] Could not find Python anywhere on this machine.
    echo.
    echo  Please install Python 3.10+ from https://www.python.org/downloads/
    echo  and make sure to tick "Add Python to PATH" during setup.
    echo.
    echo  If Python IS installed, open a new Command Prompt and run:
    echo      python --version
    echo  to confirm it is on PATH, then re-run this launcher.
    echo.
    pause
    exit /b 1
)

echo Found Python: !PYTHON_EXE!
echo.

REM ============================================================
REM  STEP 1 -- Install / upgrade dependencies
REM ============================================================
echo [1/3] Installing / upgrading dependencies...
"!PYTHON_EXE!" -m pip install -q --upgrade pip
"!PYTHON_EXE!" -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo       Done.
echo.

REM ============================================================
REM  STEP 2 -- Kill any old Streamlit on port 8501
REM ============================================================
echo [2/3] Clearing old Streamlit process on port 8501 (if any)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo       Done.
echo.

REM ============================================================
REM  STEP 3 -- Launch Streamlit
REM ============================================================
echo [3/3] Starting Streamlit...
echo       URL: http://localhost:8501
echo.

start http://localhost:8501

"!PYTHON_EXE!" -m streamlit run app.py --server.port 8501 --server.headless false

echo.
echo Streamlit exited.
pause
