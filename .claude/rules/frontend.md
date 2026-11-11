---
paths:
  - "backend/kroger_lookup/static/**"
---

# Frontend (`backend/kroger_lookup/static/index.html`)

One file: React 18 UMD + in-browser Babel from unpkg, pinned and SRI-hashed. Bumping a version means recomputing its `integrity` hash. No build step. The "in-browser Babel transformer" console warning is expected.

## Map

- Constants: `KROGER_CHAINS` (chain filter), `DIVISIONS` (division dropdown; differs from the backend's `DIVISION_SEEDS`, see `backend.md`).
- Helpers: `API` (GET + error text), `getPricing` (public API price/stock), `sanitizeHtml`, `proxyImg`/`getImg`/`getLargeImg` (all images go through `/api/img`), `krogerStoreUrl`, `krogerUrl`.
- Components: `Lightbox`, `ProductModal`, `ProductCard` (prices, deal pills, net price), `TourOverlay`, `App` (all state and handlers: `searchStores`, `searchByDivision`, `lookupByStoreId`, `fetchDeals`, `searchProducts`, `saveSetup`, `loginElectron`, `refreshElectronCookies`).
- Deals and net price: see `deals.md`.

## Behaviour rules

- **Store-page URL** (`krogerStoreUrl`): `/stores/grocery/{state}/{city-slug}/{name-slug}/{div3}/{store5}`.
- **Store-ID input** requires exactly 8 digits, with no auto-padding.
- **UPC input** accepts at most 13 digits. Deals and atlas pricing are keyed by `upc.padStart(13,'0')`.
- **Store list filtering:** drop addresses containing `1014 vine` (Kroger HQ test stores, `INTERNAL_ADDRESSES`), and badge stores with "fuel" in the name (they have no store page).
- **Product search** (`searchProducts`): sends the full term with `limit=50`. For 2+ words it keeps only products whose description+brand contain every word, then shows 20. The original design (2026-03-20 and 03-21) specified "first word to the API, filter the rest locally"; the code changed to the full term on 3/21 after "Kroger Tortilla" missed results. `URLSearchParams` encodes `&`, so the earlier parameter-injection worry does not apply.
- **Deals** are fetched only when a store is selected and "search without store" is off, and only in Electron (`canBrowserDeals`).
- **Out of stock** (`getPricing`): only an explicit `stockLevel` of `TEMPORARILY_OUT_OF_STOCK`/`OUT_OF_STOCK`; `fulfillment.inStock` is not trusted.
- **Images:** the 3/22 `referrerPolicy="no-referrer"` + meta-tag fix did not work; the `/api/img` proxy is the real fix. The attributes remain.
- **Rendered HTML** from Kroger goes through `sanitizeHtml()`: formatting tags only (`SAFE_TAGS`), all attributes stripped, script-like elements dropped with their text.
