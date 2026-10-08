@echo off
setlocal
cd /d "%~dp0" || exit /b 1

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo ERROR: Project virtual environment not found: "%PYTHON%" 1>&2
    exit /b 2
)

if /i "%~1"=="--test-telegram" (
    "%PYTHON%" -m skills.notify --test "Telegram connection test from run.bat"
) else (
    "%PYTHON%" "%~dp0run_agent.py" %*
)
exit /b %ERRORLEVEL%