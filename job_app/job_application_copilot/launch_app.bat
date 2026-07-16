@echo off
setlocal

set "PROJECT_DIR=C:\Users\User\Downloads\job_app\job_application_copilot"
set "ANACONDA_ROOT=C:\Users\User\anaconda3\Anaconda"
set "STREAMLIT_PORT=8501"

echo.
echo ==========================================
echo Launching Job Application Copilot UI
echo ==========================================
echo PROJECT_DIR   = %PROJECT_DIR%
echo ANACONDA_ROOT = %ANACONDA_ROOT%
echo.

if not exist "%PROJECT_DIR%" (
    echo ERROR: Project folder not found:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%\app.py" (
    echo ERROR: app.py not found in:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

if not exist "%ANACONDA_ROOT%\python.exe" (
    echo ERROR: Python not found:
    echo %ANACONDA_ROOT%\python.exe
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%" || (
    echo ERROR: Could not change into project folder.
    pause
    exit /b 1
)

start "" cmd /k ""%ANACONDA_ROOT%\python.exe" -m streamlit run "%PROJECT_DIR%\app.py" --server.port %STREAMLIT_PORT%"

exit /b