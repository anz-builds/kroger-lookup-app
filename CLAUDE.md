# Kroger Price Lookup — agent guide

Product and store lookup across the Kroger banners (Ralphs, Fred Meyer, King Soopers, …).

- **Prices, products, and stores** come from Kroger's **public API** (`api.kroger.com/v1`, OAuth client credentials).
- **Deals** (BOGO, multi-buy, Yellow Tag, digital coupons) come from Kroger's **internal atlas API** (`www.kroger.com/atlas/v1`). The requests run inside a hidden kroger.com window in the Electron app, on the user's own Kroger session, so deals are desktop-only.

The reasoning behind most odd-looking code lives in the maintainer's build logs (2026-03-13 → 2026-06-22, kept outside this repo). This file caches what those build logs decided. Where code and build logs disagree, see *Code vs. build logs* at the bottom.

## Two builds, one codebase

`WEB_MODE` (`kroger-lookup/main.py:30,48`) switches between them.

| | Web (hosted) | Desktop (Electron) |
|---|---|---|
| Search, stores, store pricing | yes | yes |
| Deals | no. The deals panel becomes a "Download Desktop App" card | yes |
| Session source | none | built-in Kroger login window (`persist:kroger` partition) |
| Python deps | `requirements-web.txt` | `requirements.txt` + PyInstaller |
| Bind | `0.0.0.0:$PORT` (8000) | `127.0.0.1:18234` (`electron/main.js:7`) |
| CORS | `*` | localhost origins only |
| Setup, session, deals endpoints | 404 | localhost-only, JSON-only (`desktop_only()`) |

Running the backend in a plain browser (`python main.py`, no Electron) behaves like the web build for deals: the panel shows the Download card, because deals need `window.electronAPI.atlasFetch`. The old browser modes (Chrome CDP on port 9333, manual DevTools paste) and the curl_cffi transport were archived on 2026-10-27; see `archive/legacy-deals/`.

## Repo layout

- `kroger-lookup/` is the **canonical** backend + frontend. The Dockerfile, `build.bat`, and Electron all use it.
  - `main.py`: the entire FastAPI backend.
  - `static/index.html`: the entire frontend. React 18 UMD + in-browser Babel from unpkg, pinned and SRI-hashed (bumping a version means recomputing its `integrity` hash). No build step.
- `electron/`: `main.js` (spawns the backend, login window, cookie/LAF capture, hidden deals window), `preload.js`, `preload-login.js`, `package.json` (electron-builder config; Electron and electron-builder are pinned exact).
- Root `build.bat` / `dev.bat` / `Dockerfile` / `Procfile`: the live build entry points.
- `archive/`: stale snapshots kept for history. Nothing there is built or imported (see `archive/README.md`). Never edit archived files as if they were live.

## Architecture

- **Backend (FastAPI).**
  - Token cache: in-memory client-credentials token, refreshed 60 s before expiry, re-fetched once on 401 (`main.py:175,205`).
  - Credentials: loaded from the first `.env` found in `BASE_DIR`, `%APPDATA%\KrogerLookup`, or `~/.kroger-lookup` (`main.py:14`).
  - Session info: `_atlas_cookies` (only for the status banner) and `_atlas_laf` (the LAF captured at login) live in process globals, so they are lost on restart. Python never sends the cookies anywhere.
- **Deals flow** (`fetchDeals` in `index.html`):
  1. `POST /api/deals/plan` returns the two atlas paths (products, coupons) and the headers a page may set (`x-laf-object`, `x-modality`, `X-Facility-Id`, `User-Time-Zone: UTC`, …).
  2. `window.electronAPI.atlasFetch(path, headers)` runs each request with `fetch()` inside a hidden kroger.com `BrowserWindow` on the `persist:kroger` session (`electron/main.js`, `atlasFetch`), 1.5 s apart. Only `/atlas/v1/` paths are allowed. The browser supplies cookies, User-Agent and Referer itself.
  3. `POST /api/deals/parse` runs the raw responses through `_parse_product_promos` and `_parse_atlas_response`.
  - The hidden window has `backgroundThrottling: false`, waits 4 s after loading kroger.com, and on a `429 {"cpr_chlge":"true"}` reloads kroger.com once and retries. It is destroyed when the main window closes; otherwise Electron keeps running and locks the session profile.
- **Electron.**
  - Startup: spawns the backend (dev: `kroger-lookup/.venv/Scripts/python.exe` if present, else system Python; packaged: `resources/backend/kroger-backend.exe`). Then it polls `/api/atlas-cookies/status` for up to 20 s and opens the UI.
  - Login flow: the login window injects a blue "Done — Extract Session" banner. On click it does three things:
    1. Reads the `.kroger.com` cookies.
    2. Triggers an atlas fetch and captures the real `x-laf-object` via `webRequest.onBeforeSendHeaders` (fallback: localStorage/sessionStorage).
    3. POSTs both to `/api/atlas-cookies/electron`.
  - On each launch it re-sends the saved cookies, without the LAF.
- **Packaging.** PyInstaller `--onedir` → `kroger-lookup/dist/kroger-backend/`. electron-builder then makes a portable x64 build → `electron/dist/KrogerPriceLookup-1.0.0-portable.exe` (~190 MB, near-instant start).

## Endpoints (`kroger-lookup/main.py`)

| Route | Upstream | Does / returns |
|---|---|---|
| `GET /api/locations?zip_code&radius=10&limit=10&chain` | public `/locations` | Raw Kroger location list |
| `GET /api/locations/{location_id}` | public `/locations/{id}` | One store; `{data:null,error}` on 404 |
| `GET /api/locations/by-division/{division}?chain` | public `/locations` ×N | Whole division (see Data rules); adds `_storeNumber`, `_divisionNumber`; `meta.count` |
| `GET /api/products?term|upc&location_id&limit≤50&start` | public `/products` | Raw product list; prices only when `location_id` is given |
| `GET /api/products/{product_id}?location_id` | public `/products/{id}` | One product |
| `POST /api/deals/plan` `{upcs, location_id, store}` 🔒 | none | `{upcs, headers, requests:[{kind:"product", path}, {kind:"coupons", path}]}` for the Electron window to fetch: atlas `/product/v2/products` and `/savings-coupons/v1/coupons`. Max 50 UPCs. |
| `POST /api/deals/parse` `{upcs, responses:{product, coupons}}` 🔒 | none | Each response is `{status, text}` or `{error}`. Returns `{upc: [deal…], _atlas_pricing: {upc:{reg,promo,outOfStock,size}}}`; adds `_error`/`_message` on a product 403 (`forbidden`) or when every request failed (`atlas_error`). |
| `POST /api/atlas-cookies/electron` `{cookies, laf}` 🔒 | none | Records the session from Electron (status banner + login LAF) |
| `GET /api/atlas-cookies/status` | none | `{set, cookieCount, akamaiTokens, hasLaf, lafLength, refreshing}`; also Electron's readiness probe |
| `GET /api/config` | none | `{webMode, needsSetup}` |
| `POST /api/setup` `{client_id, client_secret}` 🔒 | public token endpoint (verify) | Writes `.env` to `%APPDATA%\KrogerLookup` **and** next to `main.py`; reloads creds |
| `GET /api/img?url` | Kroger CDN | Image proxy, 24 h cache (the CDN blocks non-kroger.com browser requests). Allows only `https` URLs whose host is `*.kroger.com` or `*.kfrg.io`, re-checks every redirect, and returns only `image/*` responses up to 5 MB |
| `GET /` | none | Serves `static/index.html` |

🔒 = `desktop_only()` (`main.py`): 404 in `WEB_MODE`; on desktop it requires a `127.0.0.1`/`localhost` Host header (blocks DNS rebinding) and an `application/json` body (forces a CORS preflight, so other websites can't post through the user's browser). New endpoints that change server state or reach local machines must call it too.

Deal objects: `{badge, text, value, nfor?, endDate, offerId, source}`. `source` is one of `promo | offer | coupon | storePrice`.

## Data rules

- **UPC → 13 digits.** Strip non-digits, then `zfill(13)`, with no check digit added (`pad_upc`, `main.py:235`). `0002840051777` is the canonical form, and atlas matching also compares with leading zeros stripped. The frontend accepts at most 13 digits and pads with `padStart(13,'0')` when keying deals.
- **locationId** = 3-digit division + 5-digit store (`01400929` → division `014`, store `929`).
  - Store-page URL: `/stores/grocery/{state}/{city-slug}/{name-slug}/{div3}/{store5}` (`index.html:650`).
  - Store-ID input requires exactly 8 digits, with no auto-padding.
- **Division lookup.** The public API has no division filter.
  1. `DIVISION_SEEDS` (`main.py:273`) maps each division to 2–5 seed ZIPs spread across its footprint.
  2. All seeds are queried in parallel (100 mi radius, limit 200), and results are kept only if `locationId` starts with the division prefix, then de-duplicated.
  3. If the seed's `chain` filter yields 0 results, retry without it. Chain codes are unverified, which is why 701/704/708/534/620 needed this.
  4. Divisions with no seed fall back to a no-ZIP paged scan (max 600). The 3/13 build log found that scan unreliable.
- **Store list filtering** (frontend): drop addresses containing `1014 vine` (Kroger HQ test stores), and badge stores with "fuel" in the name (they have no store page).
- **Product search.**
  - `filter.term` hits a fuzzy consumer index, *not* the `description` field: exact catalog descriptions return 0 results, and size words ("party size") hurt. UPC is the only precise key.
  - The frontend sends the full term with `limit=50`. For 2+ words it keeps only products whose description+brand contain every word, then shows 20.
  - Deals are fetched only when a store is selected and "search without store" is off.
- **Atlas request requirements.**
  - Run from a real kroger.com page on the user's session (the hidden Electron window), so Akamai sees the browser that holds the cookies.
  - An `x-laf-object` header. The store chosen on kroger.com must be **Pickup**: Delivery carries no `storeId`, and atlas answers `LAF_OBJECTS_REQUIRED`.
  - If the global LAF is missing or minimal (<200 chars or no `handoffAddress`), `_atlas_headers` builds one from the sidebar store's address/geo, with modality PICKUP and `facilityId = storeId`. kroger.com uses an internal facility number instead, but tests on 2026-10-27 showed it does not change prices or offers.
  - **`User-Time-Zone: UTC`.** Offer start/end times (e.g. `"start":"2026-10-28T00:00:00"`) are read in this zone. kroger.com's server sends UTC; with `America/New_York` the new week's offers stay hidden until local midnight Wednesday.
- **Deal parsing** (`_parse_product_promos` `main.py:1170`, `_parse_atlas_response` `:1008`).
  - Promos sit at `price.storePrices.promo`, where `storePrices` may be a dict *or* a list, with the badge from `price.displayTemplate` (e.g. `BOGO`).
  - Multi-buy sits at top-level `offers[]` (`displayTemplate: MUST_BUY`), with `N/$X` parsed from `defaultDescription`.
  - Sale price fallback: `sourceLocations[].prices[].sale`.
  - Coupon badge: `specialSavings.DISPLAYNAME`, with UPPERCASE keys (`STANDARD`/`cash_back` are suppressed). Coupons match on `upcs`. If none match, all coupons broadcast to all UPCs (the API pre-filtered).
- **Out of stock.** Only an explicit `stockLevel` of `TEMPORARILY_OUT_OF_STOCK`/`OUT_OF_STOCK`, or PICKUP `availability.sellable == false`. `inventory.effective` reads 0/0 even for in-stock items, so it is ignored.
- **Net price** (`ProductCard`, `index.html:704`).
  - BOGO: half price.
  - Multi-buy: value ÷ n.
  - A `$X` in the deal text, if below retail: that is the target price.
  - Otherwise `value`: ≥ 50% of retail counts as the target price, below 50% as savings.
  - Yellow/White Tag are skipped, because the footer already shows the sale price.
- **Atlas pricing fallback.** The public API omits price for unavailable items. Cards then use `_atlas_pricing` instead.

## Run, build, deploy

- **Credentials.** Get a client ID/secret at developer.kroger.com. Either copy `kroger-lookup/.env.example` → `.env`, or use the first-run setup screen.
- **Local web/dev:** `cd kroger-lookup && python main.py`. Add `WEB_MODE=true` to mimic the hosted build.
- **Desktop dev:** root `dev.bat`. This runs `npm install` if needed, then `npm start` in `electron/`. Create the venv once:

  ```
  cd kroger-lookup
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
  ```

- **Build the exe:** root `build.bat`.
  1. Creates the venv and installs PyInstaller.
  2. Runs `.venv\Scripts\python -m PyInstaller` with the uvicorn hidden imports + `--add-data static;static`.
  3. Runs `npm run dist-win`.

  Use `python -m PyInstaller`; the bare `pyinstaller` command isn't on PATH. An empty `.env` placeholder is created so the build never bundles real keys. Upload the exe to GitHub Releases (`anz-builds/kroger-lookup-app`), which the web CTA links to.
- **Hosted web build: Northflank** (moved there from Koyeb). The old Koyeb URL in the README, `https://example.koyeb.app/`, is stale. The service builds from the repo the same way any Docker host would:
  - Builder: the root `Dockerfile` (`python:3.13-slim`, `requirements-web.txt`, `WEB_MODE=true`).
  - Env vars: `KROGER_CLIENT_ID`, `KROGER_CLIENT_SECRET`, `WEB_MODE=true`, `PORT=8000`. Expose port 8000. Credentials go *only* in the host's env vars, because `/api/setup` is disabled in web mode.
  - Northflank is linked to GitHub and rebuilds on every push to **`default`**, the only branch (`main` is a leftover). Pushing *is* the deploy. The remote is named `github`.
  - Runtime variables set in Northflank: `KROGER_CLIENT_ID`, `KROGER_CLIENT_SECRET`, `WEB_MODE`. `PORT` falls back to the Dockerfile's `8000`.
  - After a deploy, hard-refresh (Ctrl+Shift+R): the browser cache has served stale HTML before. A Varnish CDN cache also sits in front of the service (`Via: 1.1 varnish`, `X-Cache` headers), so a page that stays stale after a hard refresh points there next.

## Security model

- **Hosted (`WEB_MODE`) servers never take secrets or sessions from visitors.** Credentials come only from the host's env vars, and every 🔒 endpoint returns 404.
- **The desktop backend trusts only its own UI.** It binds `127.0.0.1`, and `desktop_only()` guards every state-changing endpoint.
- **The Electron main window shows only the app UI.** `setWindowOpenHandler` and `will-navigate` (`electron/main.js`) send every other URL to the system browser, so Kroger pages never run next to the `electronAPI` preload. The login window is the one exception, and it must browse kroger.com.
- **Rendered HTML** from Kroger (product descriptions) goes through `sanitizeHtml()` (`static/index.html`): formatting tags only, all attributes stripped.
- **Pins.** Python deps are pinned exact (`requirements*.txt`, including `starlette`). Electron and electron-builder are pinned exact. CDN scripts are pinned and SRI-hashed. npm 11 blocks dependency install scripts unless approved; `allowScripts` in `electron/package.json` approves Electron's binary download, so a version bump means re-approving it (`npm install-scripts approve electron`).
- **The hidden deals window** runs only what `atlasFetch` passes it: a `fetch()` to a path that must start with `/atlas/v1/`, with arguments passed as JSON, never spliced into code. It has no preload, so kroger.com pages there get no `electronAPI`.

## Known issues and limits

- **Starlette advisories (fixed 2026-11-09).** Starlette 0.41.3 was exposed to GHSA-7f5h-v6xp-fcq8 / CVE-2025-62727 (FileResponse Range DoS, fixed 0.49.1), GHSA-86qp-5c8j-p5mr and GHSA-jp82-jpqv-5vv3 (poisoned `request.url` / `request.url.hostname`, which `desktop_only()` reads; fixed 1.0.1 / 1.3.0), and GHSA-wqp7-x3pw-xc5r (UNC-path SSRF in StaticFiles on Windows, fixed 1.1.0). Starlette 1.10.0 covers all of them. Check `gh api "advisories?ecosystem=pip&affects=starlette"` before bumping.
- **Public API quotas.** 10,000/day for products, 1,600/day per locations endpoint. A division search uses 2–5 location calls, or double that on chain fallback.
- **Atlas 429.** A 429 with `{"cpr_chlge":"true"}` is Akamai's page check, not a quota. The hidden window got it when it fired before kroger.com's scripts had run; see the deals flow above. Rapid repeated searches can still get a session rate-limited; wait ~5 min and log in again.
- **Old deals path (archived 2026-10-27).** Python resent the Chromium session cookies with curl_cffi `firefox133`, because plain httpx gets a 403 on TLS fingerprint. That started returning `403 Session expired`. Details and the removed code are in `archive/legacy-deals/`.
- **Dev restarts.** Stopping `npm start` from a tool can leave `electron.exe` running. A second launch then shares the locked `persist:kroger` profile: the log shows `Unable to move the cache: Access is denied` / `Failed to reset the quota database`, no cookies load, and Kroger sign-in fails. Check `tasklist | grep -i electron` and stop the leftover process tree first.
- **June 2026 breakage, fixed.**
  - (a) A global `pip install` pulled Starlette 1.2.1, which breaks FastAPI 0.115.5 (`Router.__init__() got an unexpected keyword argument 'on_startup'`). Fix: a per-project `.venv`, used by `electron/main.js` and `build.bat` (commit `61ffb86`). Since 2026-11-09 the app runs FastAPI 0.133.1 + Starlette 1.10.0 (security fixes; see below). 0.133.0 is the first FastAPI release whose metadata allows Starlette 1.x, so keep FastAPI ≥ 0.133 with Starlette 1.x.
  - (b) The hosted site (then on Koyeb) broke separately: unpinned `@babel/standalone` from unpkg threw "import declarations may only appear at top level of a module". Fix: pin `react`/`react-dom@18.3.1` and `@babel/standalone@7.29.7` (commit `24250fa`).
  - Lesson: pin everything, both pip and CDN.
- **Smaller issues.**
  - The "in-browser Babel transformer" console warning is expected.
  - `@app.on_event("startup")` is deprecated in FastAPI.
  - **A placeholder `.env` hides your real credentials in dev.** `build.bat` creates an empty `kroger-lookup/.env`. The loader stops at the first `.env` that *exists* (`main.py:14`), so the empty file shadows `%APPDATA%\KrogerLookup\.env` and dev runs show the setup screen. Delete the empty file, or fill it in.
  - Windows consoles are cp1252, so print ASCII only (`[OK]`, not `✓`). Electron also sets `PYTHONIOENCODING=utf-8`.

## Code vs. build logs (and README) disagreements

1. **Dead cookie-harvest code (archived 2026-10-27).** The harvest stub, `/api/atlas-cookies/refresh`, and the misleading "Playwright"/"browser-cookie3" comments moved to `archive/legacy-deals/` with the rest of the old deals path.
2. **Leftover deps (fixed 2026-10-27).** Removed `playwright` and `pycryptodome`, pinned the rest, and dropped the kroger.com CORS origins left from the bookmarklet. `check_cookies.py` and `test_playwright.py` moved to `archive/`. Later the same day `curl-cffi` and `websockets` went too, with the curl_cffi path.
3. **Multi-word search.** The 3/20 and 3/21 build logs specified "first word to the API, filter the rest locally". The code sends the full term (changed 3/21 after "Kroger Tortilla" missed results). The 3/20 build log's `&` parameter-injection idea does not apply: `URLSearchParams` and httpx `params=` both encode `&`.
4. **Search endpoint.** The 3/20 build log says search uses the atlas product endpoint. It uses public `/v1/products`; atlas is used only for deals.
5. **Divisions.**
   - The frontend `DIVISIONS` has 25 entries and the backend `DIVISION_SEEDS` has 24. 097 Harris Teeter and 540 Ocado have no seeds and hit the unreliable scan. 625 City Market is seeded but missing from the dropdown.
   - Labels differ: 024 is Louisville vs. Mid-South; 708 is Food 4 Less (MW) vs. Foods Co.
   - Chain codes differ: `MARIANO` (frontend) vs. `MARIANOS` (backend).
   - The README claims 25 divisions including Harris Teeter.
6. **`facilityId`.** The store-built LAF sets `facilityId = storeId`, but real captures use an internal facility number (3/14: store `03400017` → `12565`; 10/27: `02900310` → `13824`). Tests on 10/27 showed the value does not change prices or offers.
7. **CDP port (archived).** The 3/18 build log started on 9222; the archived code and `.bat` used 9333.
8. **Images.** The 3/22 `referrerPolicy="no-referrer"` + meta-tag fix did not work. The `/api/img` proxy is the real fix, but the attributes remain.
9. **HTTP version.** A 3/14 build log step forced HTTP/1.1; that was reverted. The code uses default HTTP/2 with retries.
10. **Session messages.** A product 403 now says "Kroger session expired (403). Sign in to Kroger again." The Electron startup refresh sends no LAF, which clears `_atlas_laf`; deals still work because the LAF is rebuilt from the selected store.
11. **Root README.**
    - Its endpoint table lists 8 of the 13 routes.
    - Quick Start says `cd kroger-lookup/kroger-lookup`, the stale copy.
    - It says Python 3.11+, while Docker uses an unpinned `python:3.13-slim`.
    - It lists store pricing as desktop-only, though web has it.
12. **Stale build path.** The `build-backend` script in `electron/package.json` uses bare `pyinstaller`, which is not on PATH. Use `build.bat`.
13. **The 2026-04-13 build log** only says "adding more features to the kroger lookup app". It records no decisions.

## Open questions (unresolved — ask the maintainer, don't assume)

1. What is the Northflank URL? Update the README's demo link. Delete the leftover `main` branch?
2. The root README still describes the old layout and Koyeb. Rewrite it?
3. Which exe version is on GitHub Releases, and does it include the setup screen and the June fixes?
4. ~~Is browser + CDP mode still supported?~~ Resolved 2026-10-27: no. Deals are Electron-only; CDP and paste are archived.
5. ~~Remove the dead harvest code?~~ Resolved 2026-10-27: archived.
6. Has the `facilityId = storeId` approximation ever caused missing deals?
7. Are 097 and 540 unseeded on purpose? Is there a verified list of `filter.chain` values?
8. Is the dual `.env` write in `/api/setup` (APPDATA + next to `main.py`) intended?
10. Pin the Docker Python tag (e.g. `3.13.x-slim`)?
11. Should `build.bat` stop creating the empty `.env` placeholder, given that it shadows the `%APPDATA%` credentials (see Known issues)?
