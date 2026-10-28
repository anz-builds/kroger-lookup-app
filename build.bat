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
cd /d "%~dp0kroger-lookup"
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)
echo Installing dependencies into venv...
.venv\Scripts\pip install -r requirements.txt -q
.venv\Scripts\pip install pyinstaller -q
echo Done.

echo.
echo === Step 2: Bundle Python backend with PyInstaller ===
REM --onedir creates a folder with all deps (faster startup than --onefile)
REM Create empty .env if it doesn't exist (credentials set via setup screen)
if not exist ".env" (
    echo. > .env
    echo Created placeholder .env - users will configure credentials on first launch
)

.venv\Scripts\python -m PyInstaller --noconfirm --onedir --name kroger-backend ^
  --hidden-import=uvicorn.logging ^
  --hidden-import=uvicorn.lifespan ^
  --hidden-import=uvicorn.lifespan.on ^
  --hidden-import=uvicorn.lifespan.off ^
  --hidden-import=uvicorn.protocols ^
  --hidden-import=uvicorn.protocols.http ^
  --hidden-import=uvicorn.protocols.http.auto ^
  --hidden-import=uvicorn.protocols.http.h11_impl ^
  --hidden-import=uvicorn.protocols.http.httptools_impl ^
  --hidden-import=uvicorn.protocols.websockets ^
  --hidden-import=uvicorn.protocols.websockets.auto ^
  --hidden-import=uvicorn.protocols.websockets.wsproto_impl ^
  --hidden-import=uvicorn.loops ^
  --hidden-import=uvicorn.loops.auto ^
  --hidden-import=uvicorn.loops.asyncio ^
  --hidden-import=httptools ^
  --hidden-import=dotenv ^
  --add-data "static;static" ^
  main.py

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed. Check the output above.
    pause
    exit /b 1
)
echo Backend bundled to dist\kroger-backend\
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
