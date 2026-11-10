# Backend API

The backend serves the web page and a JSON API under `/api`. "Public API" means Kroger's developer API (`api.kroger.com/v1`); "Desktop only" endpoints return 404 in web mode.

## Stores

| Endpoint | Returns |
|---|---|
| `GET /api/locations?zip_code=45202&radius=10&limit=10&chain=` | Stores near a ZIP code (public API). `radius` is 1 to 100 miles, `limit` 1 to 200. |
| `GET /api/locations/{location_id}` | One store by its 8-digit ID, or `{data: null, error}` if it doesn't exist. |
| `GET /api/locations/by-division/{division}?chain=` | Every store in a division, with `_storeNumber` and `_divisionNumber` added. |

## Products

| Endpoint | Returns |
|---|---|
| `GET /api/products?term=milk&location_id=01400929&limit=10&start=1` | Products matching a search term (public API). Prices appear only when `location_id` is set. `limit` is 1 to 50. |
| `GET /api/products?upc=0002840051777&location_id=...` | Products matching a UPC. The UPC is padded to 13 digits. |
| `GET /api/products/{product_id}?location_id=...` | One product. |
| `GET /api/img?url=...` | A product image from Kroger's image servers. Only `https` addresses on `kroger.com` or `kfrg.io` are allowed. |

## Deals (desktop only)

The desktop app fetches deals inside its own kroger.com window, on your signed-in session. The backend plans the requests and reads the answers; it never contacts kroger.com itself.

| Endpoint | Does |
|---|---|
| `POST /api/deals/plan` `{upcs, location_id, store}` | Returns the two kroger.com requests (products and coupons) for up to 50 UPCs, and the headers to send. |
| `POST /api/deals/parse` `{upcs, responses}` | Reads the raw kroger.com answers and returns the deals for each UPC, plus fallback prices. |
| `POST /api/atlas-cookies/electron` `{cookies, laf}` | Records the kroger.com session the desktop app captured at sign-in. |
| `GET /api/atlas-cookies/status` | Whether a kroger.com session is recorded. |

## App

| Endpoint | Does |
|---|---|
| `GET /api/config` | `{webMode, needsSetup}`. |
| `POST /api/setup` `{client_id, client_secret}` | Desktop only. Checks the credentials with Kroger and saves them (see [configuration.md](configuration.md)). |
| `GET /` | The web page. |

Desktop-only endpoints also refuse requests that don't come from the app itself: the `Host` header must be `127.0.0.1` or `localhost`, and request bodies must be JSON.
