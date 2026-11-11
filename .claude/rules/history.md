---
paths:
  - "backend/kroger_lookup/main.py"
  - "electron/main.js"
---

# History: removed code and settled decisions

- **Old deals path (removed 2026-10-27).** Python resent the Chromium session cookies with curl_cffi `firefox133`, because plain httpx got a 403 on TLS fingerprint. That started returning `403 Session expired`. The browser modes (Chrome CDP on port 9333, manual DevTools paste) went with it. Early versions started CDP on 9222; the removed code and `.bat` used 9333. Deals now run inside the Electron Kroger window (`deals.md`).
- **Dead cookie-harvest code (removed 2026-10-27).** The harvest stub, `/api/atlas-cookies/refresh`, and the misleading "Playwright"/"browser-cookie3" comments.
- **Leftover deps (removed 2026-10-27).** `playwright`, `pycryptodome`, then `curl-cffi` and `websockets`; the kroger.com CORS origins left from the bookmarklet were dropped. The `check_cookies.py` and `test_playwright.py` diagnostics were removed.
- **Search endpoint:** an early note said search uses the atlas product endpoint. It uses public `/v1/products`.
- **Root README (rewritten 2026-11-09)** to the template's alphagov order; reference details live in `docs/`.
- **Stale build path (removed 2026-11-09).** The `build-backend` script in `electron/package.json` used bare `pyinstaller` and the old folder.
