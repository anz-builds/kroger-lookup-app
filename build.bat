@echo off
echo ============================================
echo  Kroger Price Lookup — Full Build
echo ============================================
echo.
echo This script will:
echo   1. Bundle the Python backend with PyInstaller
echo   2. Package everything into an Electron app
echo.

REM ── Step 0: Check prerequisites ──
where python >nul 2>&1 || (echo ERROR: Python not found in PATH && pause && exit /b 1)
where node >nul 2>&1 || (echo ERROR: Node.js not found in PATH && pause && exit /b 1)
where npm >nul 2>&1 || (echo ERROR: npm not found in PATH && pause && exit /b 1)

echo.
echo === Step 1: Set up venv and install Python dependencies ===
cd /d "%~dp0backend"
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)
echo Installing dependencies into venv...
.venv\Scripts\pip install --require-hashes -r requirements.txt -q
.venv\Scripts\pip install pyinstaller -q
echo Done.

echo.
echo === Step 2: Bundle Python backend with PyInstaller ===
REM No .env is bundled: credentials come from the setup screen (%%APPDATA%%\KrogerLookup\.env).
REM --onedir creates a folder with all deps (faster startup than --onefile)
.venv\Scripts\python -m PyInstaller --noconfirm --onedir --name backend ^
  --paths "%~dp0backend" ^
  --collect-submodules uvicorn ^
  --add-data "%~dp0backend\kroger_lookup\static;kroger_lookup\static" ^
  --distpath "%~dp0backend\dist" --workpath "%~dp0backend\build" --specpath "%~dp0backend\build" ^
  "%~dp0backend\kroger_lookup\__main__.py"

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. Check the output above.
    pause
    exit /b 1
)
echo Backend bundled to backend\dist\backend\
echo.

echo === Step 3: Install Electron dependencies ===
cd /d "%~dp0electron"
call npm install
echo Done.

echo.
echo === Step 4: Build Electron app ===
call npm run dist-win
if errorlevel 1 (
    echo.
    echo ERROR: Electron build failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  BUILD COMPLETE!
echo ============================================
echo.
echo Output: electron\dist\KrogerPriceLookup-*-portable.exe
echo.
dir /b dist\*.exe 2>nul
echo.
pause
