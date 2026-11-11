---
paths:
  - "backend/**"
---

# Backend (`backend/kroger_lookup/main.py`)

## Internals

- **Token cache:** in-memory client-credentials token, refreshed 60 s before expiry, re-fetched once on 401 (`get_token`, `kroger_get`).
- **One shared `httpx.AsyncClient`** (`_kroger_client`) serves every Kroger API call. The `lifespan` handler opens it at startup, after `check_credentials`, and closes it at shutdown. `TestClient(app)` without `with` skips the lifespan, so tests never open it. `/api/img` keeps its own per-request client, because it uses a different timeout and checks each redirect by hand.
- **Credentials:** loaded from the first `.env` that *exists* in `backend/` (`ENV_DIR`), `%APPDATA%\KrogerLookup`, or `~/.kroger-lookup` (`_env_paths`). An empty `backend/.env` shadows the others: if dev runs show the setup screen, check for one. Missing credentials don't stop the import; the app shows the setup screen.
- **Session globals:** `_atlas_cookies` (only for the status banner) and `_atlas_laf` (the LAF captured at login) live in process memory, so they are lost on restart. Python never sends the cookies anywhere. `_atlas_cookies_refreshing` is never set to `True`.
- **`desktop_only()`:** 404 in `WEB_MODE`; on desktop it requires a `127.0.0.1`/`localhost` Host header (blocks DNS rebinding) and an `application/json` body (forces a CORS preflight, so other websites can't post through the user's browser). Tests send `headers={"host": "127.0.0.1"}` to pass it.
- Deals planning and parsing: see `deals.md`.

## Endpoints

| Route | Upstream | Does / returns |
|---|---|---|
| `GET /api/locations?zip_code&radius=10&limit=10&chain` | public `/locations` | Raw Kroger location list |
| `GET /api/locations/{location_id}` | public `/locations/{id}` | One store; `{data:null,error}` on 404 |
| `GET /api/locations/by-division/{division}?chain` | public `/locations` ×N | Whole division (see below); adds `_storeNumber`, `_divisionNumber`; `meta.count` |
| `GET /api/products?term|upc&location_id&limit≤50&start` | public `/products` | Raw product list; prices only when `location_id` is given |
| `GET /api/products/{product_id}?location_id` | public `/products/{id}` | One product |
| `POST /api/deals/plan` 🔒 | none | Atlas request plan (`deals.md`) |
| `POST /api/deals/parse` 🔒 | none | Parsed deals (`deals.md`) |
| `POST /api/atlas-cookies/electron` `{cookies, laf}` 🔒 | none | Records the session from Electron (status banner + login LAF) |
| `GET /api/atlas-cookies/status` | none | `{set, cookieCount, akamaiTokens, hasLaf, lafLength, refreshing}`; also Electron's readiness probe |
| `GET /api/config` | none | `{webMode, needsSetup}` |
| `POST /api/setup` `{client_id, client_secret}` 🔒 | public token endpoint (verify) | Writes `.env` to `%APPDATA%\KrogerLookup` (or `~/.kroger-lookup`) **and** to `backend/.env`; reloads creds |
| `GET /api/img?url` | Kroger CDN | Image proxy, 24 h cache (the CDN blocks non-kroger.com browser requests). `_allowed_image_url`: only `https`, port 443, host `kroger.com`/`kfrg.io` or a subdomain; re-checks every redirect; only `image/*` up to 5 MB |
| `GET /` | none | Serves `static/index.html` |

🔒 = `desktop_only()`.

## Data rules

- **UPC → 13 digits.** Strip non-digits, then `zfill(13)`, with no check digit added (`pad_upc`). `0002840051777` is the canonical form; atlas matching also compares with leading zeros stripped.
- **locationId** = 3-digit division + 5-digit store (`01400929` → division `014`, store `929`).
- **Division lookup** (`locations_by_division`). The public API has no division filter.
  1. `DIVISION_SEEDS` maps each division to 2–5 seed ZIPs spread across its footprint.
  2. All seeds are queried in parallel (100 mi radius, limit 200); results are kept only if `locationId` starts with the division prefix, then de-duplicated.
  3. If the seed's `chain` filter yields 0 results, retry without it. Chain codes are unverified, which is why 701/704/708/534/620 needed this.
  4. Divisions with no seed fall back to a no-ZIP paged scan (max 600). The 3/13 build log found that scan unreliable.
  - Frontend and backend lists differ: frontend `DIVISIONS` has 25 entries, `DIVISION_SEEDS` 26. 097 Harris Teeter (chain `HART`) and 540 Ocado were seeded on 2026-11-10; 540 returns e-commerce fulfillment centers, not stores. 625 City Market is seeded but missing from the dropdown. Labels differ (024 Louisville vs. Mid-South; 708 Food 4 Less (MW) vs. Foods Co), and so do chain codes (`MARIANO` frontend vs. `MARIANOS` backend).
- **Product search.** `filter.term` hits a fuzzy consumer index, *not* the `description` field: exact catalog descriptions return 0 results, and size words ("party size") hurt. UPC is the only precise key. Search uses public `/v1/products`; atlas is used only for deals.

## Quotas

- Public API: 10,000/day for products, 1,600/day per locations endpoint. A division search uses 2–5 location calls, or double that on chain fallback.
- The hosted build caps its own use per UTC day (`spend_budget`): 8,000 product and 1,300 location calls by default (`WEB_DAILY_PRODUCT_CALLS` / `WEB_DAILY_LOCATION_CALLS`). Past the cap the API returns 429 "Daily lookup limit reached". Counts live in memory, so a redeploy resets them; one visitor can still use up the day's budget for everyone.
- CORS stops other websites from calling the hosted API through visitors' browsers. It doesn't stop scripts or `curl`; the daily cap covers those.
- Inside a division search a 429 is swallowed by `fetch_zip`, so an exhausted budget shows as 0 stores.

## History

- HTTP: a 3/14 build log step forced HTTP/1.1; that was reverted. The code uses default HTTP/2.
- A product 403 says "Kroger session expired (403). Sign in to Kroger again."
- FastAPI/Starlette compatibility and advisories: see `deploy.md`.
