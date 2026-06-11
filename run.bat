@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%PROJECT_ROOT%server.py"
    exit /b %ERRORLEVEL%
)

if exist "%BUNDLED_PYTHON%" (
    "%BUNDLED_PYTHON%" "%PROJECT_ROOT%server.py"
    exit /b %ERRORLEVEL%
)

echo Python 3.10 or newer is required. Install Python or run this inside Codex with the bundled runtime available.
exit /b 1
