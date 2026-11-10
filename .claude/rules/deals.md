---
paths:
  - "backend/kroger_lookup/main.py"
  - "backend/kroger_lookup/static/index.html"
  - "electron/main.js"
  - "backend/tests/**"
---

# Deals: atlas requests, parsing, net price

## Flow (`fetchDeals` in `index.html`)

1. `POST /api/deals/plan` (`plan_deals`) returns the two atlas paths and the headers a page may set (`_BROWSER_SETTABLE_HEADERS`: `x-laf-object`, `x-modality`, `X-Facility-Id`, `User-Time-Zone: UTC`, …). Max 50 UPCs.
   - product: `/atlas/v1/product/v2/products?filter.gtin13s=…&filter.verified=true&projections=items.full,offers.compact,inventory.projected`
   - coupons: `/atlas/v1/savings-coupons/v1/coupons?filter.upc=…&filter.type=standard&filter.type=cash_back&projections=coupons.full`
2. `window.electronAPI.atlasFetch(path, headers)` runs each request with `fetch()` inside a hidden kroger.com `BrowserWindow` on the `persist:kroger` session (`atlasFetch`, `electron/main.js`), 1.5 s apart. Only `/atlas/v1/` paths are allowed. The browser supplies cookies, User-Agent and Referer itself.
3. `POST /api/deals/parse` (`parse_deals`) runs the raw responses through `_parse_product_promos` and `_parse_atlas_response`. Each response is `{status, text}` or `{error}`. It returns `{upc: [deal…], _atlas_pricing: {upc: {reg, promo, outOfStock, size}}}`, plus `_error`/`_message` on a product 403 (`forbidden`) or when every request failed (`atlas_error`).

Python never contacts kroger.com; it only plans and parses.

The hidden window has `backgroundThrottling: false`, waits 4 s after loading kroger.com (`loadKrogerPage`), and on a `429 {"cpr_chlge":"true"}` reloads kroger.com once and retries. That 429 is Akamai's page check, not a quota: the window got it when it fired before kroger.com's scripts had run. Rapid repeated searches can still get a session rate-limited; wait about 5 min and log in again.

Deal objects: `{badge, text, value, nfor?, endDate, offerId, source}`. `source` is one of `promo | offer | coupon | storePrice`.

## Atlas request requirements

- Run from a real kroger.com page (the hidden Electron window), so Akamai sees the browser that holds the cookies.
- An `x-laf-object` header. The store chosen on kroger.com must be **Pickup**: Delivery carries no `storeId`, and atlas answers `LAF_OBJECTS_REQUIRED`.
- If the global LAF (`_atlas_laf`) is missing or minimal (<200 chars or no `handoffAddress`), `_atlas_headers` builds one from the sidebar store's address/geo, with modality PICKUP and `facilityId = storeId`. Real captures use an internal facility number instead (store `03400017` → `12565`; `02900310` → `13824`); tests on 2026-10-27 showed the value does not change prices or offers.
- **`User-Time-Zone: UTC`.** Offer start/end times (e.g. `"start":"2026-10-28T00:00:00"`) are read in this zone. kroger.com's server sends UTC; with `America/New_York` the new week's offers stay hidden until local midnight Wednesday.
- The Electron startup refresh sends no LAF, which clears `_atlas_laf`; deals still work because the LAF is rebuilt from the selected store.

### Observed 2026-11-10: sessions with no Kroger login

- In fresh Electron sessions with no sign-in, the app's planned requests got **403 Access Denied** (Akamai HTML), while kroger.com's own page calls in the same sessions returned 200.
- After a Pickup store was chosen and confirmed in kroger.com's own store picker, the same planned requests returned 200. The test fixtures were captured this way.
- No control run isolated the cause, so "a confirmed Pickup store is enough" is a lead, not a fact. kroger.com's own page calls coupons **v2**; the app uses v1.

## Deal parsing (`_parse_product_promos`, `_parse_atlas_response`)

- Promos sit at `price.storePrices.promo`, where `storePrices` may be a dict *or* a list, with the badge from `price.displayTemplate` (e.g. `BOGO`, `YellowTag`, `PriceDrop`).
- Promo `value` is `promo.nforPrice`, which arrives as a string such as `"USD 6.99"`. The frontend copes (see Net price); the tests leave it unpinned until the maintainer decides (open question in `project.md`).
- Multi-buy sits at top-level `offers[]` (`displayTemplate: MUST_BUY`, or `MEGA_EVENT`), with `N/$X` parsed from `defaultDescription` into `nfor`/`value`. "Buy 3 Get 3 Free" offers carry no `nfor`/`value`.
- Sale price fallback: `sourceLocations[].prices[].sale`.
- Coupon badge: `specialSavings` `displayName`/`DISPLAYNAME` (e.g. "Weekly Digital Deals"). `STANDARD`/`cash_back` are suppressed. Coupons match on `upcs`, comparing 13-digit and zero-stripped forms. If none match, all coupons broadcast to all UPCs (the API pre-filtered).
- **Out of stock.** Only an explicit `inventory.locations[].stockLevel` of `TEMPORARILY_OUT_OF_STOCK`/`OUT_OF_STOCK`, or PICKUP `fulfillmentSummaries[].availability.sellable == false`. `inventory.effective` reads 0/0 even for in-stock items, so it is ignored.
- **Atlas pricing fallback.** The public API omits price for unavailable items; cards then use `_atlas_pricing` (`ProductCard`).

## Net price (`ProductCard`, `index.html`)

The best deal sets `afterDealPrice` (and `afterDealQty`):

- Yellow/White Tag: skipped, because the footer already shows the sale price.
- BOGO (badge or "buy 1, get 1" in the text): half the regular price, qty 2.
- Multi-buy with `nfor > 1`: `value ÷ nfor`, if below regular.
- "Save $N each when you buy M" (MEGA_EVENT): shelf price (promo if on sale) minus N, qty M; also shown as "Save $N each (buy M+)".
- A `$X` in the deal text, if below regular: that is the target price.
- Otherwise the digits in `value` (`"USD 3.79"` → 3.79): ≥ 50% of regular counts as the target price, below 50% as savings.
- Untested gap: a promo with `nfor > 1` and a string `value` fails the multi-buy check (`d.value > 0` on a string) and falls through to the text rule. No such promo has been seen in a capture yet.

## Test fixtures (`backend/tests/fixtures/`)

- `atlas_product.json` and `atlas_coupons.json`: unmodified atlas response bodies for store `01400929` (Kroger - University Plaza), captured 2026-11-10 from a session with no Kroger login, using the app's planned requests. `atlas_capture.json` records the UPCs and request paths.
- They cover Yellow Tag, Price Drop, MEGA_EVENT, Buy 3 Get 3, Buy 2 Get 1, 4/$10, a digital coupon, one out-of-stock item, and an item with no deal. `test_deal_parsing.py` names the UPC for each.
- No personal fields. Before adding a capture from a signed-in session, remove loyalty IDs, names and email addresses.
