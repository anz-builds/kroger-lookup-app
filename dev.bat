@echo off
echo ============================================
echo  Kroger Price Lookup — Dev Mode
echo ============================================
echo.
echo This runs the app in development mode:
echo   - Python FastAPI backend (live reload)
echo   - Electron frontend with login window
echo.
echo Press Ctrl+C to stop.
echo.

REM Install electron if needed
cd /d "%~dp0electron"
if not exist node_modules (
    echo Installing Electron dependencies...
    call npm install
)

echo Starting Electron (will auto-start Python backend)...
call npm start
