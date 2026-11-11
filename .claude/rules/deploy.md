---
paths:
  - "Dockerfile"
  - "Procfile"
  - ".github/**"
  - "build.bat"
  - "build.sh"
  - "electron/package.json"
  - "backend/pyproject.toml"
  - "backend/requirements*.txt"
---

# Dependencies, builds, releases, hosting

## Pins

Every Python dependency, transitive ones included, is pinned exact with hashes. Edit only the top-level pins in `backend/pyproject.toml`, then regenerate both lock files from the repo root:

```
uv pip compile backend/pyproject.toml --universal --python-version 3.13 --generate-hashes -o backend/requirements.txt
uv pip compile backend/pyproject.toml --extra dev --universal --python-version 3.13 --generate-hashes -o backend/requirements-dev.txt
```

`--universal` writes platform markers, so one file serves Windows, macOS (`build.sh`) and Linux (Docker). `requirements-dev.txt` adds pytest. Hash-checking mode rejects any package whose file doesn't match. Electron and electron-builder are pinned exact; CDN scripts are pinned and SRI-hashed.

- **FastAPI/Starlette:** the app runs FastAPI 0.133.1 + Starlette 1.10.0 (2026-11-09). 0.133.0 is the first FastAPI release whose metadata allows Starlette 1.x, so keep FastAPI ≥ 0.133 with Starlette 1.x.
- **Starlette advisories (fixed 2026-11-09).** 0.41.3 was exposed to GHSA-7f5h-v6xp-fcq8 / CVE-2025-62727 (FileResponse Range DoS, fixed 0.49.1), GHSA-86qp-5c8j-p5mr and GHSA-jp82-jpqv-5vv3 (poisoned `request.url` / `request.url.hostname`, which `desktop_only()` reads; fixed 1.0.1 / 1.3.0), and GHSA-wqp7-x3pw-xc5r (UNC-path SSRF in StaticFiles on Windows, fixed 1.1.0). 1.10.0 covers all of them. Check `gh api "advisories?ecosystem=pip&affects=starlette"` before bumping.
- **June 2026 breakage, fixed.** (a) A global `pip install` pulled Starlette 1.2.1, which broke FastAPI 0.115.5 (`Router.__init__() got an unexpected keyword argument 'on_startup'`); fix: the per-project `backend/.venv`, used by `electron/main.js` and the build scripts (commit `f006ff4`). (b) The hosted site broke on unpinned `@babel/standalone` ("import declarations may only appear at top level of a module"); fix: pin `react`/`react-dom@18.3.1` and `@babel/standalone@7.29.7` (commit `6b4389f`). Lesson: pin everything.

## Desktop builds

- **Windows:** root `build.bat`. It creates `backend/.venv`, installs `requirements.txt` with hashes plus PyInstaller, runs `.venv\Scripts\python -m PyInstaller --onedir --name backend --collect-submodules uvicorn --add-data …\kroger_lookup\static;kroger_lookup\static`, then `npm run dist-win`. Use `python -m PyInstaller`; the bare `pyinstaller` command isn't on PATH. Output: `electron/dist/KrogerPriceLookup-<version>-portable.exe` (~190 MB).
- **macOS / Linux:** `./build.sh` (arm64 dmg, ad-hoc signed; x64 AppImage). PyInstaller builds only for the system it runs on.
- PyInstaller output `backend/dist/backend/` is copied by electron-builder to `resources/backend/` (`extraResources`).
- No `.env` is bundled; the packaged app reads `%APPDATA%\KrogerLookup\.env` (setup screen). The build scripts no longer create an empty `.env` placeholder (fixed 2026-11-09; it shadowed the APPDATA file).
- User-facing build and first-launch steps live in `docs/building.md`.

## CI and releases

- `.github/workflows/tests.yml`: pytest on every PR and on pushes to `default` (Ubuntu, Python 3.13, `requirements-dev.txt` with hashes).
- `.github/workflows/release.yml`: on a `v*` tag, builds Windows (portable exe), macOS (arm64 dmg) and Linux (x64 AppImage) on GitHub runners, then creates the GitHub release. The tag must match `electron/package.json`'s version. All `dist-*` scripts pass `--publish never`. v1.1.0 was released this way.
- Actions are pinned by commit SHA with the version in a comment; copy those pins when adding a workflow.

## Hosted web build: Northflank

- Live URL `https://p01--kroger-lookup--xrzr292k2mfz.code.run` (moved from Koyeb; the old URL is gone). `WEB_ORIGIN` in `main.py` must match it.
- Builder: the root `Dockerfile` (`python:3.13-slim`, `backend/requirements.txt`, `WEB_MODE=true`, `CMD python -m kroger_lookup`). Wheels only, runs as the unprivileged user `app` (uid 10001).
- Runtime variables: `KROGER_CLIENT_ID`, `KROGER_CLIENT_SECRET`, `WEB_MODE`; `PORT` falls back to the Dockerfile's `8000`. Credentials go only in the host's env vars, because `/api/setup` is disabled in web mode.
- Northflank rebuilds on every push to **`default`**, the only branch. Pushing *is* the deploy. The remote is named `github`.
- After a deploy, hard-refresh (Ctrl+Shift+R): the browser cache has served stale HTML before. A Varnish CDN cache also sits in front (`Via: 1.1 varnish`, `X-Cache` headers), so a page that stays stale after a hard refresh points there next.
