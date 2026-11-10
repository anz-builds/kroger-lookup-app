#!/usr/bin/env bash
# Kroger Price Lookup: full build on macOS (Apple Silicon .dmg) or Linux (x64 AppImage).
#   1. Bundle the Python backend with PyInstaller (one folder, backend/dist/backend/)
#   2. Package it into an Electron app (electron/dist/)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Step 0: Check prerequisites ──
command -v python3 >/dev/null || { echo "ERROR: python3 not found in PATH"; exit 1; }
command -v node >/dev/null || { echo "ERROR: Node.js not found in PATH"; exit 1; }
command -v npm >/dev/null || { echo "ERROR: npm not found in PATH"; exit 1; }

echo "=== Step 1: Set up venv and install Python dependencies ==="
cd "$ROOT/backend"
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
.venv/bin/pip install --require-hashes -r requirements.txt -q
.venv/bin/pip install pyinstaller -q

echo "=== Step 2: Bundle Python backend with PyInstaller ==="
# No .env is bundled: credentials come from the setup screen (~/.kroger-lookup/.env).
# --onedir creates a folder with all deps (faster startup than --onefile)
.venv/bin/python -m PyInstaller --noconfirm --onedir --name backend \
  --paths "$ROOT/backend" \
  --collect-submodules uvicorn \
  --add-data "$ROOT/backend/kroger_lookup/static:kroger_lookup/static" \
  --distpath "$ROOT/backend/dist" --workpath "$ROOT/backend/build" --specpath "$ROOT/backend/build" \
  "$ROOT/backend/kroger_lookup/__main__.py"
echo "Backend bundled to backend/dist/backend/"

echo "=== Step 3: Install Electron dependencies ==="
cd "$ROOT/electron"
npm install

echo "=== Step 4: Build Electron app ==="
if [ "$(uname -s)" = "Darwin" ]; then
  npm run dist-mac
else
  npm run dist-linux
fi

echo "BUILD COMPLETE!"
ls dist/*.dmg dist/*.AppImage 2>/dev/null || true
