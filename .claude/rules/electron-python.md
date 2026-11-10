---
paths:
  - "backend/**"
  - "electron/**"
  - "Dockerfile"
  - "build.*"
---

# Electron + Python Backend

- Layout: `backend/` is a FastAPI app in a flat package (`backend/<package>/`), with its tests in `backend/tests/`. `electron/` is the desktop shell, packaged with electron-builder. The root `Dockerfile` runs the same backend as a web service.
- The desktop app ships the backend as a PyInstaller one-folder build (`backend/dist/backend/`). electron-builder copies it into the app's `resources/backend/` via `extraResources`, and `electron/main.js` starts it from `process.resourcesPath`.
- Dependencies: declare them in `backend/pyproject.toml` with exact versions. Regenerate both hashed lock files from the repo root after every change (needs uv):
  `uv pip compile backend/pyproject.toml --universal --python-version 3.13 --generate-hashes -o backend/requirements.txt`
  `uv pip compile backend/pyproject.toml --extra dev --universal --python-version 3.13 --generate-hashes -o backend/requirements-dev.txt`
- Set up: `python -m venv backend/.venv`, then install `backend/requirements-dev.txt` into it with `pip install --require-hashes -r`. In `electron/`, run `npm install`.
- Run the backend alone: `python -m <package>` from `backend/` (binds 127.0.0.1; set `WEB_MODE=true` to bind 0.0.0.0). Run the desktop app: `npm start` in `electron/`. Test: `python -m pytest` from `backend/`.
- Build the desktop app: `./build.sh` (macOS/Linux) or `build.bat` (Windows). Build the web image: `docker build -t <name> .` from the repo root.
