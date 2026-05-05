@echo off
setlocal
rem Go up one level from scripts/ to the project root
cd /d "%~dp0.."

echo.
echo ============================================================
echo   Fearoff AIAD -- GST Compliance Platform
echo ============================================================
echo.

rem Check if Docker is running
docker info >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker Desktop is not running!
    echo.
    echo Please start Docker Desktop before running this project.
    echo 1. Search for 'Docker Desktop' in your Start menu.
    echo 2. Wait for it to show 'Engine Running'.
    echo 3. Run this script again.
    echo.
    pause
    exit /b 1
)

rem Activate virtual environment if exists
if exist venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

rem Run start_frappe_server.py from scripts/
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Starting Fearoff AIAD...
    py scripts\start_frappe_server.py %*
) else (
    echo Using python to start Fearoff AIAD...
    python scripts\start_frappe_server.py %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to start the server.
    echo Please ensure Python is installed and Docker is configured correctly.
    echo See docs\STARTUP_TROUBLESHOOTING.md for help.
)

echo.
pause
endlocal
