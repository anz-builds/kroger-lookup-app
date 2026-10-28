#!/usr/bin/env bash
# Kroger Price Lookup — full macOS build (Apple Silicon). Run on a Mac.
# The Mac counterpart of build.bat:
#   1. Bundle the Python backend with PyInstaller
#   2. Package everything into an Electron .dmg
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Step 0: Check prerequisites ──
command -v python3 >/dev/null || { echo "ERROR: python3 not found in PATH"; exit 1; }
command -v node >/dev/null || { echo "ERROR: Node.js not found in PATH"; exit 1; }
command -v npm >/dev/null || { echo "ERROR: npm not found in PATH"; exit 1; }

echo "=== Step 1: Set up venv and install Python dependencies ==="
cd "$ROOT/kroger-lookup"
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
.venv/bin/pip install -r requirements.txt -q
.venv/bin/pip install pyinstaller -q

echo "=== Step 2: Bundle Python backend with PyInstaller ==="
# No empty .env placeholder here (build.bat makes one): PyInstaller doesn't bundle it,
# and in dev it would shadow ~/.kroger-lookup/.env. Credentials come from the setup screen.
# --onedir creates a folder with all deps (faster startup than --onefile)
.venv/bin/python -m PyInstaller --noconfirm --onedir --name kroger-backend \
  --hidden-import=uvicorn.logging \
  --hidden-import=uvicorn.lifespan \
  --hidden-import=uvicorn.lifespan.on \
  --hidden-import=uvicorn.lifespan.off \
  --hidden-import=uvicorn.protocols \
  --hidden-import=uvicorn.protocols.http \
  --hidden-import=uvicorn.protocols.http.auto \
  --hidden-import=uvicorn.protocols.http.h11_impl \
  --hidden-import=uvicorn.protocols.http.httptools_impl \
  --hidden-import=uvicorn.protocols.websockets \
  --hidden-import=uvicorn.protocols.websockets.auto \
  --hidden-import=uvicorn.protocols.websockets.wsproto_impl \
  --hidden-import=uvicorn.loops \
  --hidden-import=uvicorn.loops.auto \
  --hidden-import=uvicorn.loops.asyncio \
  --hidden-import=httptools \
  --hidden-import=dotenv \
  --add-data "static:static" \
  main.py
echo "Backend bundled to kroger-lookup/dist/kroger-backend/"

echo "=== Step 3: Install Electron dependencies ==="
cd "$ROOT/electron"
npm install

echo "=== Step 4: Build Electron app ==="
npm run dist-mac

echo "BUILD COMPLETE!"
echo "Output: electron/dist/KrogerPriceLookup-*-arm64.dmg"
ls dist/*.dmg 2>/dev/null || true
