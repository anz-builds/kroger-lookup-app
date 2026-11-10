---
paths:
  - "archive/**"
---

# History: archived code and settled decisions

`archive/` holds stale snapshots. Nothing there is built or imported; `archive/README.md` maps each folder. Its last line still names the old root `kroger-lookup/` folder; the live code is now in `backend/`.

- **Old deals path (archived 2026-10-27, `archive/legacy-deals/`).** Python resent the Chromium session cookies with curl_cffi `firefox133`, because plain httpx got a 403 on TLS fingerprint. That started returning `403 Session expired`. The browser modes (Chrome CDP on port 9333, manual DevTools paste) went with it. The 3/18 build log started CDP on 9222; the archived code and `.bat` used 9333. Deals now run inside the Electron Kroger window (`deals.md`).
- **Dead cookie-harvest code (archived 2026-10-27).** The harvest stub, `/api/atlas-cookies/refresh`, and the misleading "Playwright"/"browser-cookie3" comments.
- **Leftover deps (removed 2026-10-27).** `playwright`, `pycryptodome`, then `curl-cffi` and `websockets`; the kroger.com CORS origins left from the bookmarklet were dropped. `check_cookies.py` and `test_playwright.py` moved to `archive/`.
- **3/20 build log** said search uses the atlas product endpoint. It uses public `/v1/products`.
- **Root README (rewritten 2026-11-09)** to the template's alphagov order; reference details live in `docs/`.
- **Stale build path (removed 2026-11-09).** The `build-backend` script in `electron/package.json` used bare `pyinstaller` and the old folder.
- **The 2026-04-13 build log** only says "adding more features to the kroger lookup app". It records no decisions.
