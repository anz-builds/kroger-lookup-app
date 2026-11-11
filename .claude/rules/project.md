# Kroger Price Lookup — agent guide (core)

Product and store lookup across the Kroger banners (Ralphs, Fred Meyer, King Soopers, …).

- **Prices, products, and stores** come from Kroger's **public API** (`api.kroger.com/v1`, OAuth client credentials).
- **Deals** (BOGO, multi-buy, Yellow Tag, digital coupons) come from Kroger's **internal atlas API** (`www.kroger.com/atlas/v1`). The requests run inside a hidden kroger.com window in the Electron app, so deals are desktop-only.

The reasoning behind most odd-looking code lives in the maintainer's build logs (2026-03-13 → 2026-06-22, kept outside this repo). These rule files cache what those build logs decided. `main.py` means `backend/kroger_lookup/main.py`; `index.html` means `backend/kroger_lookup/static/index.html`. Cite code by function name, not line number.

## Topic files

These load automatically when you touch the files they cover (`paths:` frontmatter). Read the matching one by hand when a task spans topics before touching any file.

| File | Covers | Loads for |
|---|---|---|
| `deals.md` | Deals flow, atlas request rules, deal parsing, net price, fixtures, capture findings | `main.py`, `index.html`, `electron/main.js`, `backend/tests/` |
| `backend.md` | FastAPI internals, endpoints, credentials, divisions, product search, quotas | `backend/` |
| `frontend.md` | The single-page React UI | `backend/kroger_lookup/static/` |
| `electron.md` | Desktop shell: startup, login window, hidden deals window, dev gotchas | `electron/`, `dev.bat`, build scripts |
| `deploy.md` | Pins, lock files, builds, releases, CI, the hosted web build | `Dockerfile`, `.github/`, build scripts, dependency files |
| `history.md` | Removed code paths and settled code-vs-build-log disagreements | `main.py`, `electron/main.js` |

`docs.md` and `electron-python.md` beside them come from the Copier template; leave them as they are.

## Two builds, one codebase

`WEB_MODE` (`main.py`) switches between them.

| | Web (hosted) | Desktop (Electron) |
|---|---|---|
| Search, stores, store pricing | yes | yes |
| Deals | no. The deals panel becomes a "Download Desktop App" card | yes |
| Session source | none | built-in Kroger login window (`persist:kroger` partition) |
| Python deps | `backend/requirements.txt` | `backend/requirements.txt` + PyInstaller |
| Bind | `0.0.0.0:$PORT` (8000) | `127.0.0.1:18234` (`FASTAPI_PORT`, `electron/main.js`) |
| CORS | the Northflank origin only (`WEB_ORIGIN`) | localhost origins only |
| Setup, session, deals endpoints | 404 | localhost-only, JSON-only (`desktop_only()`) |

Running the backend in a plain browser (`python -m kroger_lookup` from `backend/`, no Electron) behaves like the web build for deals: the panel shows the Download card, because deals need `window.electronAPI.atlasFetch`.

## Repo layout

- From the `anz-builds/project-template` Copier template (layers `base` and `electron-python`, v0.6.0). Never edit `.copier-answers*.yml` by hand.
- `backend/`: the Python project. `kroger_lookup/main.py` is the entire FastAPI backend; `kroger_lookup/__main__.py` starts it and is the PyInstaller entry point; `kroger_lookup/static/index.html` is the entire frontend (no build step).
- `backend/tests/`: pytest. Smoke tests (`test_app.py`), helper tests (`test_helpers.py`), and deal parsing against real captured atlas responses (`test_deal_parsing.py`, `fixtures/`). No test calls Kroger.
- `electron/`: `main.js`, `preload.js`, `preload-login.js`, `package.json` (electron-builder config).
- Root `build.bat` / `build.sh` / `dev.bat` / `Dockerfile` / `Procfile`: the live build entry points.

## Security model

These hold across every change:

- **Hosted (`WEB_MODE`) servers never take secrets or sessions from visitors.** Credentials come only from the host's env vars, and every desktop-only endpoint returns 404.
- **The desktop backend trusts only its own UI.** It binds `127.0.0.1`, and `desktop_only()` guards every state-changing endpoint. New endpoints that change server state or reach local machines must call it too.
- **The Electron main window shows only the app UI.** Kroger pages never run next to the `electronAPI` preload; the login window is the one exception.
- **Rendered HTML from Kroger** goes through `sanitizeHtml()` in `index.html`.
- **Pin everything**, pip and CDN alike (details in `deploy.md`).

## Run and test

- Credentials: a client ID/secret from developer.kroger.com, in `backend/.env` (copy `backend/.env.example`) or via the first-run setup screen.
- Backend only: `cd backend && .venv\Scripts\python -m kroger_lookup`. Add `WEB_MODE=true` to mimic the hosted build.
- Desktop dev: root `dev.bat` (runs `npm install` if needed, then `npm start` in `electron/`).
- Tests: `cd backend && .venv\Scripts\python -m pytest`. Run them once more with `WEB_MODE=true`: the desktop-only tests then skip.
- Create the venv once: `cd backend`, `python -m venv .venv`, `.venv\Scripts\pip install --require-hashes -r requirements-dev.txt`.
- Windows consoles are cp1252: print ASCII only (`[OK]`, not `✓`).

## Open questions (ask the maintainer, don't assume)

None.

## To do

- Pin the Docker Python tag (`Dockerfile` uses `python:3.13-slim`) and PyInstaller (`build.bat` and `build.sh` install it unpinned), per "Pin everything".

## Settled (2026-11-10)

- No `main` branch exists; `default` is the only branch, locally and on GitHub.
- `facilityId = storeId` makes no difference to prices or offers (tested 2026-10-28; see `deals.md`).
- Divisions 097 (Harris Teeter) and 540 (Ocado) are seeded (`88ae4d8`). 540 returns e-commerce fulfillment centers, not stores.
- The dual `.env` write in `/api/setup` is an intended fallback (comment in `save_credentials`).
