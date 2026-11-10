---
paths:
  - "electron/**"
  - "dev.bat"
  - "build.bat"
  - "build.sh"
---

# Electron shell (`electron/main.js`)

## Startup

- Spawns the backend on port `FASTAPI_PORT` (18234). Dev: `python -m kroger_lookup` with `backend/.venv` if present, else system Python, with `WEB_MODE` cleared so it binds `127.0.0.1`. Packaged: `resources/backend/backend.exe` (`backend` on macOS/Linux). Both get `PYTHONIOENCODING=utf-8`.
- Polls `/api/atlas-cookies/status` for up to 20 s, then opens the main window.
- Sets the `persist:kroger` session's user agent to plain Chrome (`plainChromeUserAgent` strips the app name and `Electron/<version>`), because Kroger's bot protection can flag them.
- Re-sends the saved Kroger cookies to the backend (`refreshCookies`), without the LAF.

## Windows

- **Main window:** shows only the app UI. `setWindowOpenHandler` and `will-navigate` send every other URL to the system browser, so Kroger pages never run next to the `electronAPI` preload (`preload.js`). Closing it destroys the hidden deals window; otherwise Electron keeps running and locks the session profile.
- **Login window** (`openLoginWindow`, `persist:kroger`, `preload-login.js`): starts on the kroger.com homepage, not `/signin` (a fresh session landing on `/signin` may be refused). It counts as logged in after a visit to `login.kroger.com`/`/signin` followed by a return to `www.kroger.com`. It injects a blue banner; after login the banner's "Done — Extract Session" button runs `extractAndSendCookies`:
  1. Reads the `.kroger.com` cookies.
  2. Triggers an atlas fetch and captures the real `x-laf-object` via `webRequest.onBeforeSendHeaders` (8 s timeout; fallback: localStorage/sessionStorage).
  3. POSTs both to `/api/atlas-cookies/electron`.
- **Hidden deals window** (`getDealsWindow`, `atlasFetch`): see `deals.md`. It runs only a `fetch()` to a path that must start with `/atlas/v1/`, with arguments passed as JSON, never spliced into code. It has no preload, so kroger.com pages there get no `electronAPI`.

## IPC (`preload.js` → `electronAPI`)

`login`, `refreshCookies`, `getCookieCount`, `atlasFetch`, `clearSession`, `onCookiesUpdated`, `isElectron`. The login window gets only `electronLoginAPI.extractAndClose`.

## Gotchas

- **Dev restarts.** Stopping `npm start` from a tool can leave `electron.exe` running. A second launch then shares the locked `persist:kroger` profile: the log shows `Unable to move the cache: Access is denied` / `Failed to reset the quota database`, no cookies load, and Kroger sign-in fails. Check `tasklist | grep -i electron` and stop the leftover process tree first.
- Electron 45 has no install script: it downloads its binary on the first `npm start` (`node_modules/electron/index.js`), so the `allowScripts` entry in `electron/package.json` is a no-op.
- Builds and packaging: see `deploy.md`.
