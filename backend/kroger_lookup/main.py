import os
import time
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# backend/ in a source checkout, where the dev .env sits next to .env.example
ENV_DIR = BASE_DIR.parent

# Look for .env in multiple locations (packaged exe may be in a different dir)
_env_paths = [
    ENV_DIR / ".env",
    Path(os.environ.get("APPDATA", "")) / "KrogerLookup" / ".env",
    Path.home() / ".kroger-lookup" / ".env",
]
_active_env_path = None
for _ep in _env_paths:
    if _ep.exists():
        load_dotenv(_ep)
        _active_env_path = _ep
        break

from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

# One shared HTTP client for Kroger API calls (token + kroger_get), opened and closed with the app
_kroger_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _kroger_client
    await check_credentials()
    _kroger_client = httpx.AsyncClient(timeout=TIMEOUT)
    try:
        yield
    finally:
        await _kroger_client.aclose()


app = FastAPI(title="Kroger Product Lookup", lifespan=lifespan)

_web_mode = os.getenv("WEB_MODE", "").lower() in ("true", "1", "yes")
# Hosted build: only the Northflank site itself may call the API from a browser
WEB_ORIGIN = "https://p01--kroger-lookup--xrzr292k2mfz.code.run"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[WEB_ORIGIN] if _web_mode else [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:18234",
        "http://127.0.0.1:18234",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

CLIENT_ID = os.getenv("KROGER_CLIENT_ID") or ""
CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET") or ""
BASE_URL = "https://api.kroger.com/v1"
WEB_MODE = os.getenv("WEB_MODE", "").lower() in ("true", "1", "yes")

TIMEOUT = httpx.Timeout(connect=20.0, read=30.0, write=10.0, pool=5.0)

_token_cache = {"access_token": None, "expires_at": 0}

# Hosted build: daily cap on Kroger API calls, kept below Kroger's quotas (10,000/day products,
# 1,600/day per locations endpoint) so visitors can't spend the whole quota. In-memory, UTC day,
# resets on redeploy.
WEB_DAILY_BUDGET = {
    "/products": int(os.getenv("WEB_DAILY_PRODUCT_CALLS", "8000")),
    "/locations": int(os.getenv("WEB_DAILY_LOCATION_CALLS", "1300")),
}
_budget_used = {"day": "", "/products": 0, "/locations": 0}


def spend_budget(path: str) -> None:
    """Count one upstream call in WEB_MODE; 429 once the day's budget for that API is used up."""
    if not WEB_MODE:
        return
    kind = "/products" if path.startswith("/products") else "/locations"
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _budget_used["day"] != today:
        _budget_used.update({"day": today, "/products": 0, "/locations": 0})
    if _budget_used[kind] >= WEB_DAILY_BUDGET[kind]:
        raise HTTPException(429, "Daily lookup limit reached for this site. Try again tomorrow (UTC).")
    _budget_used[kind] += 1

# Kroger session reported by the Electron app (for the status banner) and the LAF it captured
# at login. The deal requests themselves run inside the Electron Kroger window.
_atlas_cookies: str = ""
_atlas_laf: str = ""
_atlas_cookies_refreshing: bool = False


async def check_credentials():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("[SETUP] Kroger API credentials not found - app will show setup screen")
        print(f"[SETUP] Searched: {', '.join(str(p) for p in _env_paths)}")
        return
    print(f"[OK] Credentials loaded (CLIENT_ID: {CLIENT_ID[:8]}...)")
    if WEB_MODE:
        print("[OK] Running in WEB_MODE - atlas/deals features disabled")


async def get_token() -> str:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(503, "API credentials not configured. Complete setup first.")
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]
    try:
        resp = await _kroger_client.post(
            f"{BASE_URL}/connect/oauth2/token",
            data={"grant_type": "client_credentials", "scope": "product.compact"},
            auth=(CLIENT_ID, CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise HTTPException(502, f"Token fetch failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = now + data.get("expires_in", 1800)
        return _token_cache["access_token"]
    except HTTPException:
        raise
    except httpx.ConnectTimeout:
        raise HTTPException(504, "Connection to api.kroger.com timed out. Check network/VPN connectivity.")
    except httpx.ConnectError as e:
        raise HTTPException(502, f"Could not reach api.kroger.com: {e}")
    except Exception as e:
        raise HTTPException(502, f"Token request error: {e}")


async def kroger_get(path: str, params: dict) -> dict:
    spend_budget(path)
    token = await get_token()
    try:
        resp = await _kroger_client.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if resp.status_code == 401:
            _token_cache["access_token"] = None
            token = await get_token()
            resp = await _kroger_client.get(
                f"{BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Kroger API error ({resp.status_code}): {resp.text}")
        return resp.json()
    except HTTPException:
        raise
    except httpx.ConnectTimeout:
        raise HTTPException(504, "Connection to api.kroger.com timed out. Check network/VPN connectivity.")
    except httpx.ConnectError as e:
        raise HTTPException(502, f"Could not reach api.kroger.com: {e}")
    except Exception as e:
        raise HTTPException(502, f"Request error: {e}")


_LOCAL_HOSTS = ("127.0.0.1", "localhost")


def desktop_only(request: Request, require_json: bool = True) -> None:
    """Guard for endpoints that change server state or reach local machines (setup, atlas session, CDP).
    Hosted (WEB_MODE) servers hide them entirely. Desktop requires a localhost Host header
    (blocks DNS rebinding) and a JSON body (forces a CORS preflight, so other sites can't post via
    the user's browser with a text/plain "simple" request)."""
    if WEB_MODE:
        raise HTTPException(404, "Not found")
    if (request.url.hostname or "") not in _LOCAL_HOSTS:
        raise HTTPException(403, "Only allowed from localhost")
    if require_json and not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Content-Type must be application/json")


def pad_upc(upc: str) -> str:
    """Normalize UPC to 13-digit zero-padded string."""
    digits = "".join(c for c in upc.strip() if c.isdigit())
    return digits.zfill(13)


@app.get("/api/locations")
async def search_locations(
    zip_code: str = Query(..., description="ZIP code to search near"),
    radius: int = Query(10, ge=1, le=100),
    limit: int = Query(10, ge=1, le=200),
    chain: str = Query(None, description="Filter by chain name, e.g. KROGER"),
):
    params = {
        "filter.zipCode.near": zip_code,
        "filter.radiusInMiles": radius,
        "filter.limit": limit,
    }
    if chain:
        params["filter.chain"] = chain
    return await kroger_get("/locations", params)


@app.get("/api/locations/{location_id}")
async def get_location_by_id(location_id: str):
    """Fetch a single store's details by location ID (e.g. 01400929)."""
    try:
        data = await kroger_get(f"/locations/{location_id}", {})
        return data
    except HTTPException as e:
        if e.status_code == 404:
            return {"data": None, "error": "Location not found"}
        raise


# Multiple seed ZIPs per division for broad geographic coverage.
# Each list contains ZIPs spread across the division's footprint so parallel
# fetches at 100mi radius collectively cover the entire division.
DIVISION_SEEDS = {
    "011": {
        "name": "Kroger Atlanta",
        "chain": "KROGER",
        "zips": ["30301", "31401", "30901"],           # Atlanta, Savannah, Augusta
    },
    "014": {
        "name": "Kroger Cincinnati",
        "chain": "KROGER",
        "zips": ["45202", "45402"],                     # Cincinnati, Dayton
    },
    "016": {
        "name": "Kroger Columbus",
        "chain": "KROGER",
        "zips": ["43215", "43604"],                     # Columbus, Toledo
    },
    "018": {
        "name": "Kroger Michigan",
        "chain": "KROGER",
        "zips": ["48201", "49503", "48601"],            # Detroit, Grand Rapids, Saginaw
    },
    "021": {
        "name": "Kroger Central",
        "chain": "KROGER",
        "zips": ["46201", "61602", "46601"],            # Indianapolis, Peoria, South Bend
    },
    "024": {
        "name": "Kroger Mid-South",
        "chain": "KROGER",
        "zips": ["40201", "37902", "37701"],            # Louisville, Knoxville, Maryville
    },
    "025": {
        "name": "Kroger Delta",
        "chain": "KROGER",
        "zips": ["39201", "72201", "70112"],            # Jackson MS, Little Rock, New Orleans
    },
    "026": {
        "name": "Kroger Nashville",
        "chain": "KROGER",
        "zips": ["37201", "35801", "37402"],            # Nashville, Huntsville, Chattanooga
    },
    "029": {
        "name": "Kroger Mid-Atlantic",
        "chain": "KROGER",
        "zips": ["23219", "27601", "20001", "29401"],   # Richmond, Raleigh, DC, Charleston SC
    },
    "034": {
        "name": "Kroger Houston",
        "chain": "KROGER",
        "zips": ["77001", "77840", "77901"],            # Houston, Bryan, Victoria
    },
    "035": {
        "name": "Kroger Dallas",
        "chain": "KROGER",
        "zips": ["75201", "76101", "78201"],            # Dallas, Fort Worth, San Antonio
    },
    "090": {
        "name": "Ruler Foods / Jay C",
        "chain": "RULER",
        "zips": ["46201", "47201", "61401"],            # Indianapolis, Columbus IN, Galesburg IL
    },
    "097": {
        "name": "Harris Teeter",
        "chain": "HART",
        "zips": ["28202", "27601", "23219", "21401", "29577"],  # Charlotte, Raleigh, Richmond, Annapolis, Myrtle Beach
    },
    "531": {
        "name": "Mariano's",
        "chain": "MARIANOS",
        "zips": ["60601", "60201"],                     # Chicago, Evanston
    },
    "534": {
        "name": "Pick 'n Save / Roundy's",
        "chain": "PICK_N_SAVE",
        "zips": ["53201", "54301", "53401"],            # Milwaukee, Green Bay, Racine
    },
    "540": {
        "name": "Ocado",
        "chain": "KROGER",
        "zips": ["45202", "28202", "30301", "32801", "75201"],  # Cincinnati, Charlotte, Atlanta, Orlando, Dallas
    },
    "615": {
        "name": "Dillons",
        "chain": "DILLONS",
        "zips": ["67201", "66801", "64801"],            # Wichita, Emporia, Pittsburg KS
    },
    "620": {
        "name": "King Soopers",
        "chain": "KING_SOOPERS",
        "zips": ["80201", "80901", "80521"],            # Denver, Colorado Springs, Fort Collins
    },
    "625": {
        "name": "City Market",
        "chain": "CITY_MARKET",
        "zips": ["81601", "81501", "81301"],            # Glenwood Springs, Grand Junction, Durango
    },
    "660": {
        "name": "Fry's",
        "chain": "FRYS",
        "zips": ["85001", "85701", "85281"],            # Phoenix, Tucson, Tempe
    },
    "701": {
        "name": "Fred Meyer",
        "chain": "FRED_MEYER",
        "zips": ["97201", "98101", "83701", "99501"],   # Portland, Seattle, Boise, Anchorage
    },
    "703": {
        "name": "Ralphs",
        "chain": "RALPHS",
        "zips": ["90001", "92101", "93401"],            # LA, San Diego, San Luis Obispo
    },
    "704": {
        "name": "Food 4 Less",
        "chain": "FOOD_4_LESS",
        "zips": ["90001", "60601", "89101"],            # LA, Chicago, Las Vegas
    },
    "705": {
        "name": "QFC",
        "chain": "QFC",
        "zips": ["98101", "97201"],                     # Seattle, Portland
    },
    "706": {
        "name": "Smith's",
        "chain": "SMITHS",
        "zips": ["84101", "89101", "85001", "87101", "83701"],  # SLC, Las Vegas, Phoenix, Albuquerque, Boise
    },
    "708": {
        "name": "Foods Co",
        "chain": "FOODS_CO",
        "zips": ["93701", "95814", "92701"],            # Fresno, Sacramento, Santa Ana
    },
}


@app.get("/api/locations/by-division/{division}")
async def locations_by_division(
    division: str,
    chain: str = Query(None, description="Override chain filter"),
):
    """
    Fetch the complete store list for a division.
    Fires parallel requests from multiple seed ZIPs spread across the division geography,
    then deduplicates and returns all matching stores with parsed store numbers.
    locationId format: [3-digit division][5-digit store number]
    """
    import asyncio

    division_clean = division.strip().zfill(3)
    prefix = division_clean
    seed_info = DIVISION_SEEDS.get(division_clean)

    async def fetch_zip(zip_code: str, chain_filter: str) -> list:
        params = {
            "filter.zipCode.near": zip_code,
            "filter.radiusInMiles": 100,
            "filter.limit": 200,
        }
        if chain_filter:
            params["filter.chain"] = chain_filter
        try:
            data = await kroger_get("/locations", params)
            return [s for s in data.get("data", []) if s.get("locationId", "").startswith(prefix)]
        except Exception:
            return []

    if seed_info:
        effective_chain = chain or seed_info.get("chain") or None
        # Fire all seed ZIP requests concurrently
        results = await asyncio.gather(*[fetch_zip(z, effective_chain) for z in seed_info["zips"]])
        all_stores = [store for batch in results for store in batch]

        # If chain filter yielded 0 results, retry WITHOUT chain filter
        if not all_stores and effective_chain:
            print(f"  Division {division_clean}: 0 results with chain={effective_chain}, retrying without chain filter")
            results = await asyncio.gather(*[fetch_zip(z, None) for z in seed_info["zips"]])
            all_stores = [store for batch in results for store in batch]
    else:
        # Unknown division — fall back to no-ZIP paginated scan
        all_stores = []
        params: dict = {"filter.limit": 200}
        if chain:
            params["filter.chain"] = chain
        for start in range(1, 601, 200):
            params["filter.start"] = start
            data = await kroger_get("/locations", params)
            batch = data.get("data", [])
            if not batch:
                break
            all_stores += [s for s in batch if s.get("locationId", "").startswith(prefix)]
            if len(batch) < 200:
                break

    # Deduplicate, parse store number, sort
    seen = set()
    unique = []
    for s in all_stores:
        lid = s.get("locationId", "")
        if lid and lid not in seen:
            seen.add(lid)
            s["_storeNumber"] = lid[3:].lstrip("0") or "0"
            s["_divisionNumber"] = division_clean
            unique.append(s)

    if unique:
        print(f"  Sample location keys: {list(unique[0].keys())}")

    unique.sort(key=lambda s: s.get("locationId", ""))

    return {
        "data": unique,
        "meta": {
            "division": division_clean,
            "count": len(unique),
        }
    }


@app.get("/api/products")
async def search_products(
    term: str = Query(None, description="Product name or description"),
    upc: str = Query(None, description="UPC code (will be zero-padded to 13 digits)"),
    location_id: str = Query(None, description="Kroger locationId for pricing"),
    limit: int = Query(10, ge=1, le=50),
    start: int = Query(1, ge=1),
):
    if not term and not upc:
        raise HTTPException(400, "Provide either 'term' or 'upc'")

    params: dict = {"filter.limit": limit, "filter.start": start}
    params["filter.term"] = pad_upc(upc) if upc else term
    if location_id:
        params["filter.locationId"] = location_id

    return await kroger_get("/products", params)


@app.get("/api/products/{product_id}")
async def get_product(
    product_id: str,
    location_id: str = Query(None),
):
    params = {}
    if location_id:
        params["filter.locationId"] = location_id
    return await kroger_get(f"/products/{product_id}", params)


@app.get("/api/atlas-cookies/status")
async def atlas_cookie_status():
    """Check whether atlas cookies have been set."""
    if not _atlas_cookies:
        return {"set": False, "refreshing": _atlas_cookies_refreshing}
    keys = [c.split("=")[0].strip() for c in _atlas_cookies.split(";") if "=" in c]
    bm = sum(1 for k in keys if k.startswith("bm_") or k == "_abck")
    return {"set": True, "cookieCount": len(keys), "akamaiTokens": bm,
            "hasLaf": bool(_atlas_laf), "lafLength": len(_atlas_laf),
            "refreshing": _atlas_cookies_refreshing}


@app.post("/api/atlas-cookies/electron")
async def set_atlas_cookies_electron(request: Request):
    """Accept cookies from Electron's session API — no parsing needed, already clean."""
    global _atlas_cookies, _atlas_laf
    desktop_only(request)
    body = await request.json()
    cookie_str = (body.get("cookies") or "").strip()
    laf_str = (body.get("laf") or "").strip()

    if not cookie_str:
        raise HTTPException(400, "No cookies provided")

    _atlas_cookies = cookie_str

    # Use LAF from Electron if available
    if laf_str and "handoffLocation" in laf_str:
        _atlas_laf = laf_str
        print(f"  Electron: set LAF ({len(laf_str)} chars)")
    else:
        _atlas_laf = ""
        print("  Electron: no LAF provided (will build from store selection)")

    keys = [c.split("=")[0].strip() for c in _atlas_cookies.split(";") if "=" in c]
    bm = sum(1 for k in keys if k.startswith("bm_") or k == "_abck")
    print(f"  Electron: loaded {len(keys)} cookies ({bm} Akamai)")
    return {"ok": True, "cookieCount": len(keys), "akamaiTokens": bm,
            "source": "electron", "hasLaf": bool(_atlas_laf), "lafLength": len(_atlas_laf)}


def _atlas_headers(location_id: str, upcs: list = None, store_data: dict = None) -> dict:
    """Headers for atlas API requests made by the Electron Kroger window (which adds its own
    cookies, User-Agent and Referer).
    Priority for LAF: 1) Full LAF captured at Electron login  2) Built from store_data"""
    import json as _j, re as _re

    h = {
        "Accept": "application/json, text/plain, */*",
        # kroger.com's own server sends UTC; offer start/end times are read in this zone
        "User-Time-Zone": "UTC",
        "X-Kroger-Channel": "WEB",
        "x-call-origin": '{"component":"internal search","page":"internal search"}',
    }

    # Determine the best LAF to use
    laf_to_use = _atlas_laf
    laf_source = "global"

    # If _atlas_laf looks minimal (< 200 chars, no handoffAddress) and we have store_data,
    # build a proper LAF from the store
    if store_data and isinstance(store_data, dict) and store_data.get("locationId"):
        laf_is_minimal = not _atlas_laf or len(_atlas_laf) < 200 or "handoffAddress" not in _atlas_laf
        if laf_is_minimal:
            sid = str(store_data["locationId"])
            addr = store_data.get("address") or {}
            geo = store_data.get("geolocation") or {}

            laf_obj = [{
                "modality": {
                    "type": "PICKUP",
                    "handoffLocation": {
                        "storeId": sid,
                        "facilityId": sid,  # Often same as storeId for PICKUP
                    },
                    "handoffAddress": {
                        "address": {
                            "addressLines": [addr.get("addressLine1", "")],
                            "cityTown": addr.get("city", ""),
                            "name": store_data.get("name", ""),
                            "postalCode": addr.get("zipCode", ""),
                            "stateProvince": addr.get("state", ""),
                            "residential": False,
                            "countryCode": "US",
                        },
                        "location": {
                            "lat": geo.get("latitude", 0),
                            "lng": geo.get("longitude", 0),
                        }
                    }
                },
                "sources": [{"storeId": sid, "facilityId": sid}],
                "listingKeys": [sid],
            }]
            laf_to_use = _j.dumps(laf_obj)
            laf_source = "store_data"
            print(f"  Built LAF from store data: store={sid}, {len(laf_to_use)} chars")

    if laf_to_use:
        h["x-laf-object"] = laf_to_use
        try:
            laf_data = _j.loads(laf_to_use)[0]
            mod_type = laf_data.get("modality", {}).get("type", "PICKUP")
            modality_obj = {"type": mod_type}
            hand_addr = laf_data.get("modality", {}).get("handoffAddress", {})
            location = hand_addr.get("location", {})
            address = hand_addr.get("address", {})
            if location.get("lat"):
                modality_obj["lat"] = location["lat"]
            if location.get("lng"):
                modality_obj["lng"] = location["lng"]
            if address.get("postalCode"):
                modality_obj["postalCode"] = address["postalCode"]
            store_id = laf_data.get("modality", {}).get("handoffLocation", {}).get("storeId", "")
            if store_id:
                modality_obj["locationId"] = store_id
            h["x-modality"] = _j.dumps(modality_obj)
        except Exception:
            mod_type = "PICKUP"
        h["x-modality-type"] = mod_type
        # Use store ID from LAF for facility ID
        try:
            sid = _j.loads(laf_to_use)[0].get("modality", {}).get("handoffLocation", {}).get("storeId", "")
            if sid:
                h["X-Facility-Id"] = sid
        except Exception:
            pass
    elif location_id:
        # No LAF at all — set basic headers from location_id
        h["x-modality-type"] = "PICKUP"
        h["x-modality"] = _j.dumps({"type": "PICKUP", "locationId": location_id})
        h["X-Facility-Id"] = location_id

    return h


def _parse_atlas_response(data: dict, upcs: list) -> dict:
    """
    Parse atlas coupons response into { upc: [deal, ...] }.
    Response structure from kroger.com: {"data": {"coupons": [...]}, "meta": {...}}
    """
    import json as _json

    result = {upc: [] for upc in upcs}
    upc_set = set(upcs)
    upc_stripped = {u.lstrip("0"): u for u in upcs}

    # ── Unwrap nested response structure ──
    # Top level is {"data": {"coupons": [...]}, "meta": {...}}
    inner = data
    if isinstance(inner.get("data"), dict):
        inner = inner["data"]
    elif isinstance(inner.get("data"), list):
        # Some responses might nest coupons as data: [...]
        print(f"  Parser: data['data'] is a list of {len(inner['data'])} items")
        coupons_list = inner["data"]
        # Check if these are coupon objects directly
        if coupons_list and isinstance(coupons_list[0], dict):
            inner = {"coupons": coupons_list}

    coupons = inner.get("coupons") or inner.get("offers") or []
    print(f"  Parser: coupons type={type(coupons).__name__} len={len(coupons) if isinstance(coupons, (list, dict)) else 'N/A'}"
          f" (from inner keys: {list(inner.keys()) if isinstance(inner, dict) else 'not a dict'})")
    if isinstance(coupons, dict):
        # Shouldn't happen after the unwrap, but safety net
        coupons = list(coupons.values())
    # Flatten if we accidentally got a list-of-lists
    if coupons and isinstance(coupons[0], list):
        coupons = [item for sublist in coupons for item in sublist]

    if coupons:
        sample = coupons[0] if isinstance(coupons[0], dict) else {}
        print(f"  Atlas coupon sample keys: {sorted(sample.keys())}")
        # Log any UPC-looking fields from the first coupon
        upc_fields = {k: v for k, v in sample.items()
                      if any(x in k.lower() for x in ("upc", "product", "item", "sku", "gtin"))}
        if upc_fields:
            print(f"  Atlas UPC-related fields: { {k: str(v)[:120] for k,v in upc_fields.items()} }")
        else:
            print(f"  Atlas: no UPC-related fields found in coupon object")
            print(f"  Atlas first coupon (full): {_json.dumps(sample)[:1500]}")
    else:
        print(f"  Parser: coupons list is empty — no deals in atlas response for these UPCs")

    unmatched_coupons = []
    _logged_sample = False

    for coupon in coupons:
        if not isinstance(coupon, dict):
            continue

        # ── Collect UPCs this coupon applies to ──
        coupon_upcs = []

        # Direct UPC fields (many possible names)
        for field in ("upcs", "upcList", "requirementUpcs", "productUpcs",
                      "qualifyingUpcs", "qualifyingProductUpcs", "associatedUpcs",
                      "upc", "gtin", "gtins"):
            val = coupon.get(field)
            if isinstance(val, list):
                coupon_upcs.extend(val)
            elif isinstance(val, (str, int)):
                coupon_upcs.append(val)

        # Nested product/item objects
        for key in ("product", "products", "item", "items",
                    "qualifyingProducts", "requirements"):
            nested = coupon.get(key)
            if isinstance(nested, list):
                for n in nested:
                    if isinstance(n, dict):
                        for f in ("upcs", "upc", "upcList", "gtin"):
                            v = n.get(f)
                            if isinstance(v, list):
                                coupon_upcs.extend(v)
                            elif isinstance(v, (str, int)):
                                coupon_upcs.append(v)
            elif isinstance(nested, dict):
                for f in ("upcs", "upc", "upcList", "gtin"):
                    v = nested.get(f)
                    if isinstance(v, list):
                        coupon_upcs.extend(v)
                    elif isinstance(v, (str, int)):
                        coupon_upcs.append(v)

        # ── Build deal object ──
        # specialSavings contains event labels like "5X Event"
        special = coupon.get("specialSavings") or ""
        if isinstance(special, list):
            # List of dicts — grab displayName from first entry
            for s in special:
                if isinstance(s, dict):
                    special = (s.get("displayName") or s.get("DISPLAYNAME")
                               or s.get("name") or s.get("NAME") or "")
                    break
            else:
                special = ", ".join(str(s) for s in special if s)
        elif isinstance(special, dict):
            special = (special.get("displayName") or special.get("DISPLAYNAME")
                       or special.get("name") or special.get("NAME")
                       or special.get("label") or special.get("LABEL") or "")

        # Prefer specialSavings (e.g. "5X Event") over generic type ("STANDARD")
        badge = special.strip() if special and special.strip() else ""
        if not badge:
            badge = (coupon.get("badgeText") or coupon.get("promotionTypeDescription")
                     or coupon.get("displayType") or "")
        # Skip generic badges
        if badge.lower() in ("standard", "cash_back", "cashback", ""):
            badge = ""

        description = (coupon.get("displayDescription") or coupon.get("description") or
                       coupon.get("title") or coupon.get("summary") or
                       coupon.get("shortDescription") or "")
        savings = coupon.get("value") or coupon.get("savings") or coupon.get("rewardValue")
        deal = {
            "badge": badge or None,
            "text": description,
            "value": savings,
            "endDate": coupon.get("endDate") or coupon.get("expirationDate") or coupon.get("displayEndDate"),
            "offerId": coupon.get("offerId") or coupon.get("couponId") or coupon.get("id"),
            "brand": coupon.get("brand"),
            "source": "coupon",
        }

        # Log first coupon's badge-relevant fields for debugging
        if not _logged_sample:
            _logged_sample = True
            badge_fields = {k: v for k, v in coupon.items()
                           if any(x in k.lower() for x in ("badge", "type", "event", "promotion", "display", "special", "saving"))}
            print(f"  Coupon badge fields: {badge_fields}")

        # ── Match to requested UPCs ──
        matched = False
        for raw_upc in coupon_upcs:
            norm = str(raw_upc).strip().zfill(13)
            stripped = norm.lstrip("0")
            if norm in upc_set:
                result[norm].append(deal)
                matched = True
            elif stripped in upc_stripped:
                result[upc_stripped[stripped]].append(deal)
                matched = True

        if not matched:
            unmatched_coupons.append(deal)

    # ── Fallback: if API was filtered by UPC but coupons lack UPC fields,
    #    the API already did the filtering — assign unmatched coupons to all UPCs ──
    if unmatched_coupons and not any(result[u] for u in upcs):
        print(f"  Atlas: {len(unmatched_coupons)} coupons found but none matched UPCs — "
              f"applying broadcast fallback (API pre-filtered)")
        for upc in upcs:
            result[upc] = list(unmatched_coupons)

    return result


def _parse_product_promos(data: dict, upcs: list) -> tuple:
    """
    Parse atlas PRODUCT response for promotional deals AND pricing.
    Returns: (deals_dict, pricing_dict)
      deals:   { upc: [deal, ...] }
      pricing: { upc: { "reg": float, "promo": float|None, "outOfStock": bool } }
    """
    result = {upc: [] for upc in upcs}
    atlas_pricing = {}
    upc_set = set(upcs)
    upc_stripped = {u.lstrip("0"): u for u in upcs}

    products = []
    inner = data.get("data", data)
    if isinstance(inner, dict):
        products = inner.get("products") or []
    elif isinstance(inner, list):
        products = inner

    print(f"  Product parser: {len(products)} products in response")
    if upcs:
        print(f"  Product parser: looking for UPCs (first 5): {upcs[:5]}")

    match_count = 0
    no_promo_count = 0

    for idx, product in enumerate(products):
        if not isinstance(product, dict):
            continue

        pid = str(product.get("id") or product.get("upc") or product.get("gtin13") or "").strip()
        if not pid:
            continue

        # Log first 3 products for debugging
        if idx < 3:
            import json as _jj
            prod_keys = sorted(product.keys())
            price_obj = product.get("price") or {}
            price_keys = list(price_obj.keys()) if isinstance(price_obj, dict) else "N/A"
            has_promo = "promo" in price_obj if isinstance(price_obj, dict) else False
            sp_list = price_obj.get("storePrices") or []
            sp_has_promo = any(isinstance(sp, dict) and "promo" in sp for sp in sp_list)
            print(f"  Product[{idx}]: id={pid} top_keys={prod_keys}")
            print(f"  Product[{idx}]: price_keys={price_keys} has_promo={has_promo} storePrices_promo={sp_has_promo}")
            if sp_has_promo:
                for sp in sp_list:
                    if isinstance(sp, dict) and "promo" in sp:
                        print(f"  Product[{idx}].storePrices[].promo: {_jj.dumps(sp['promo'])[:400]}")
                        break
            # Log offers field
            offers = product.get("offers") or product.get("offer") or []
            if offers:
                print(f"  Product[{idx}].offers: type={type(offers).__name__} len={len(offers) if isinstance(offers, list) else 'N/A'}")
                if isinstance(offers, list) and offers:
                    print(f"  Product[{idx}].offers[0]: {_jj.dumps(offers[0])[:500]}")
                elif isinstance(offers, dict):
                    print(f"  Product[{idx}].offers: {_jj.dumps(offers)[:500]}")
            else:
                print(f"  Product[{idx}]: no 'offers' field")

        # Normalize product ID to match our UPC format
        norm_pid = pid.zfill(13)
        stripped_pid = norm_pid.lstrip("0")

        # Find matching UPC
        matched_upc = None
        if norm_pid in upc_set:
            matched_upc = norm_pid
        elif stripped_pid in upc_stripped:
            matched_upc = upc_stripped[stripped_pid]

        if not matched_upc:
            if idx < 3:
                print(f"  Product[{idx}]: NO MATCH — norm={norm_pid} not in UPC set")
            continue

        match_count += 1

        # ── Extract pricing from storePrices (available even for out-of-stock items) ──
        price = product.get("price") or {}
        store_prices_raw = price.get("storePrices") or []

        # Normalize: storePrices can be a dict {regular: {...}, ...} or a list [{...}, ...]
        sp_entries = []
        if isinstance(store_prices_raw, dict):
            # Dict format: extract regular.price and optional promo/sale price
            reg_obj = store_prices_raw.get("regular") or {}
            promo_obj = store_prices_raw.get("promo") or {}
            if isinstance(reg_obj, dict):
                promo_p = promo_obj.get("price") if isinstance(promo_obj, dict) else None
                # Also check sourceLocations[].prices[].sale for sale price
                if not promo_p:
                    for sl in (product.get("sourceLocations") or []):
                        if not isinstance(sl, dict):
                            continue
                        for slp in (sl.get("prices") or []):
                            if isinstance(slp, dict) and isinstance(slp.get("sale"), dict):
                                promo_p = slp["sale"].get("price")
                                break
                        if promo_p:
                            break
                sp_entries.append({
                    "price": reg_obj.get("price") or reg_obj.get("unitPrice") or reg_obj.get("nforPrice"),
                    "promoPrice": promo_p,
                })
        elif isinstance(store_prices_raw, list):
            sp_entries = store_prices_raw

        for sp in sp_entries:
            if not isinstance(sp, dict):
                continue
            reg = sp.get("price") or sp.get("regularPrice") or sp.get("basePrice")
            promo_price = sp.get("promoPrice") or sp.get("salePrice")
            if isinstance(reg, str):
                import re as _r
                m = _r.search(r'[\d.]+', reg)
                reg = float(m.group()) if m else None
            if isinstance(promo_price, str):
                import re as _r
                m = _r.search(r'[\d.]+', promo_price)
                promo_price = float(m.group()) if m else None
            if reg is not None:
                # Check inventory/availability from multiple sources
                out_of_stock = False
                inv = product.get("inventory") or {}
                # Check inventory.locations[].stockLevel (explicit OOS flags)
                inv_locs = inv.get("locations") or []
                if isinstance(inv_locs, list):
                    for iloc in inv_locs:
                        if isinstance(iloc, dict) and iloc.get("stockLevel", "").upper() in ("TEMPORARILY_OUT_OF_STOCK", "OUT_OF_STOCK"):
                            out_of_stock = True
                            break
                # NOTE: inventory.effective is unreliable (shows 0/0 even for in-stock items) — skip it
                # Check fulfillmentSummaries PICKUP sellable as secondary signal
                fulfillment = product.get("fulfillmentSummaries") or []
                if isinstance(fulfillment, list) and not out_of_stock:
                    pickup_fs = [fs for fs in fulfillment if isinstance(fs, dict) and fs.get("type") == "PICKUP"]
                    if pickup_fs:
                        avail = pickup_fs[0].get("availability") or {}
                        if avail.get("sellable") == False:
                            out_of_stock = True

                atlas_pricing[matched_upc] = {
                    "reg": float(reg) if reg else None,
                    "promo": float(promo_price) if promo_price else None,
                    "outOfStock": out_of_stock,
                    "size": product.get("item", {}).get("customerFacingSize") if isinstance(product.get("item"), dict) else None,
                }
                break  # Use first store price entry

        # Extract promo from price object
        price = product.get("price") or {}
        promo = price.get("promo")  # Sometimes directly on price
        store_prices_raw2 = price.get("storePrices") or []
        badge = price.get("displayTemplate") or ""  # e.g. "BOGO"
        offer_code = price.get("offerCode") or ""

        # Check storePrices promo — handle both dict and list formats
        if not promo:
            if isinstance(store_prices_raw2, dict) and store_prices_raw2.get("promo"):
                promo = store_prices_raw2["promo"]
            elif isinstance(store_prices_raw2, list):
                for sp in store_prices_raw2:
                    if isinstance(sp, dict) and sp.get("promo"):
                        promo = sp["promo"]
                        break

        if promo and isinstance(promo, dict):
            desc = (promo.get("defaultDescription") or promo.get("description")
                    or promo.get("promoDescription") or "")
            if not badge:
                badge = promo.get("type") or "SALE"

            deal = {
                "badge": badge,
                "text": desc,
                "value": promo.get("nforPrice") or promo.get("savings") or promo.get("value"),
                "nfor": promo.get("nfor"),
                "endDate": promo.get("endDate") or promo.get("expirationDate"),
                "offerId": offer_code or promo.get("offerId"),
                "source": "promo",
            }
            result[matched_upc].append(deal)

        # ── Extract from top-level offers[] (MUST_BUY / multi-buy offers like "4/$10") ──
        offers_list = product.get("offers") or []
        if isinstance(offers_list, list):
            for offer in offers_list:
                if not isinstance(offer, dict):
                    continue
                offer_desc = offer.get("defaultDescription") or offer.get("description") or ""
                offer_template = offer.get("displayTemplate") or ""
                offer_end = offer.get("end") or ""
                if offer.get("endDate") and isinstance(offer["endDate"], dict):
                    offer_end = offer["endDate"].get("value") or offer_end

                # Parse "4/$10" pattern from description
                import re as _r
                nfor_match = _r.search(r'(\d+)/\$(\d+(?:\.\d+)?)', offer_desc)
                offer_value = None
                offer_nfor = None
                if nfor_match:
                    offer_nfor = int(nfor_match.group(1))
                    offer_value = float(nfor_match.group(2))

                deal = {
                    "badge": offer_template or "MUST_BUY",
                    "text": offer_desc,
                    "value": offer_value,
                    "nfor": offer_nfor,
                    "endDate": offer_end,
                    "offerId": offer.get("offerCode") or offer.get("requirementId"),
                    "source": "offer",
                }
                # Avoid duplicates if promo already captured same deal
                existing_texts = {d.get("text", "").lower() for d in result[matched_upc]}
                if offer_desc.lower() not in existing_texts:
                    result[matched_upc].append(deal)

        # Fallback: check for sale price fields directly on storePrices (only if no deals found yet)
        if not result[matched_upc] and sp_entries:
            for sp in sp_entries:
                if not isinstance(sp, dict):
                    continue
                sale_price = sp.get("promoPrice") or sp.get("salePrice")
                reg_price = sp.get("price") or sp.get("regularPrice") or sp.get("basePrice")
                if sale_price and reg_price and sale_price != reg_price:
                    deal = {
                        "badge": badge or "SALE",
                        "text": f"Sale ${sale_price}" if isinstance(sale_price, (int, float)) else str(sale_price),
                        "value": sale_price,
                        "source": "storePrice",
                    }
                    result[matched_upc].append(deal)
                    break

        if not result[matched_upc]:
            no_promo_count += 1

    matched = sum(1 for v in result.values() if v)
    print(f"  Product parser: {match_count} ID matches, {no_promo_count} without promos, {matched}/{len(upcs)} UPCs have deals, {len(atlas_pricing)} with atlas pricing")
    return result, atlas_pricing


# ── Deals (Electron) ──
# The Electron app runs the atlas requests inside its own logged-in kroger.com window, so the
# session is used by the browser that created it. Python only plans the requests and parses
# the responses.

# Headers a page's fetch() may set; the browser supplies Cookie, User-Agent, Referer and Sec-*.
_BROWSER_SETTABLE_HEADERS = {"accept", "x-kroger-channel", "x-call-origin", "user-time-zone",
                             "x-laf-object", "x-modality", "x-modality-type", "x-facility-id"}


@app.post("/api/deals/plan")
async def plan_deals(request: Request):
    """Return the atlas paths and headers for a UPC batch, for the Electron window to fetch."""
    from urllib.parse import urlencode
    desktop_only(request)
    body = await request.json()
    upcs = [str(u).strip().zfill(13) for u in body.get("upcs", [])][:50]
    location_id = (body.get("location_id") or "").strip()
    headers = _atlas_headers(location_id, upcs, store_data=body.get("store"))
    browser_headers = {k: v for k, v in headers.items() if k.lower() in _BROWSER_SETTABLE_HEADERS}

    product_params = [("filter.gtin13s", upc) for upc in upcs]
    product_params += [("filter.verified", "true"),
                       ("projections", "items.full,offers.compact,inventory.projected")]
    coupon_params = [("filter.upc", upc) for upc in upcs]
    coupon_params += [("filter.type", "standard"), ("filter.type", "cash_back"),
                      ("projections", "coupons.full")]
    return {
        "upcs": upcs,
        "headers": browser_headers,
        "requests": [
            {"kind": "product", "path": "/atlas/v1/product/v2/products?" + urlencode(product_params)},
            {"kind": "coupons", "path": "/atlas/v1/savings-coupons/v1/coupons?" + urlencode(coupon_params)},
        ],
    }


@app.post("/api/deals/parse")
async def parse_deals(request: Request):
    """Parse atlas responses fetched by the Electron window into {upc: [deal, ...], _atlas_pricing}."""
    import json as _json
    desktop_only(request)
    body = await request.json()
    upcs = [str(u).strip().zfill(13) for u in body.get("upcs", [])][:50]
    responses = body.get("responses") or {}
    result = {upc: [] for upc in upcs}
    pricing_data = {}
    errors = []

    for kind in ("product", "coupons"):
        resp = responses.get(kind) or {}
        status = resp.get("status")
        if resp.get("error"):
            errors.append(f"{kind}: {resp['error']}")
            continue
        if status != 200:
            print(f"  In-browser {kind} API {status}: {str(resp.get('text', ''))[:300]}")
            errors.append(f"{kind}: HTTP {status}")
            if status == 403 and kind == "product":
                return {"_error": "forbidden", "_status": 403,
                        "_message": "Kroger session expired (403). Sign in to Kroger again.",
                        **result}
            continue
        try:
            raw = _json.loads(resp.get("text") or "")
        except ValueError:
            errors.append(f"{kind}: response was not JSON")
            continue
        if kind == "product":
            promos, atlas_pricing = _parse_product_promos(raw, upcs)
            pricing_data.update(atlas_pricing)
            parsed = promos
        else:
            parsed = _parse_atlas_response(raw, upcs)
        for upc, deals in parsed.items():
            if deals:
                result[upc].extend(deals)

    matched = sum(1 for v in result.values() if v)
    print(f"In-browser deals: {matched}/{len(upcs)} UPCs have deals, {len(pricing_data)} with atlas pricing")
    out = {**result, "_atlas_pricing": pricing_data}
    if errors and not matched and not pricing_data:
        out["_error"] = "atlas_error"
        out["_message"] = "Deals request failed: " + "; ".join(errors)
    return out

@app.get("/api/config")
async def get_config():
    """Return app configuration for frontend mode detection."""
    return {
        "webMode": WEB_MODE,
        "needsSetup": not CLIENT_ID or not CLIENT_SECRET,
    }


@app.post("/api/setup")
async def save_credentials(request: Request):
    """Save Kroger API credentials to a persistent .env file.
    Desktop only: a hosted (WEB_MODE) server takes credentials from its env vars, never from visitors.
    Requiring a JSON body from a localhost Host blocks other websites from posting here via the
    user's browser (text/plain CSRF, DNS rebinding)."""
    global CLIENT_ID, CLIENT_SECRET
    desktop_only(request)
    body = await request.json()
    cid = (body.get("client_id") or "").strip()
    secret = (body.get("client_secret") or "").strip()

    if not cid or not secret:
        raise HTTPException(400, "Both client_id and client_secret are required")

    # Determine save location; use %APPDATA% only when it resolves inside the user's home folder
    home = Path.home().resolve()
    appdata = Path(os.environ.get("APPDATA") or home).resolve()
    if os.name == 'nt' and appdata.is_relative_to(home):
        save_dir = home / appdata.relative_to(home) / "KrogerLookup"
    else:
        save_dir = home / ".kroger-lookup"
    save_dir.mkdir(parents=True, exist_ok=True)
    env_path = save_dir / ".env"

    # Also save next to the backend as fallback
    local_env = ENV_DIR / ".env"

    env_content = f"KROGER_CLIENT_ID={cid}\nKROGER_CLIENT_SECRET={secret}\n"

    for p in [env_path, local_env]:
        try:
            p.write_text(env_content)
            print(f"[SETUP] Saved credentials to {p}")
        except Exception as e:
            print(f"[SETUP] Could not save to {p}: {e}")

    # Update in-memory credentials
    CLIENT_ID = cid
    CLIENT_SECRET = secret
    os.environ["KROGER_CLIENT_ID"] = cid
    os.environ["KROGER_CLIENT_SECRET"] = secret

    # Clear token cache so next API call uses new credentials
    _token_cache["access_token"] = None
    _token_cache["expires_at"] = 0

    # Test credentials
    try:
        token = await get_token()
        return {"ok": True, "message": "Credentials saved and verified!", "envPath": str(env_path)}
    except Exception as e:
        return {"ok": False, "message": f"Credentials saved but verification failed: {e}. Check your Client ID and Secret."}


from starlette.responses import StreamingResponse
import io

_IMG_HOST_SUFFIXES = ("kroger.com", "kfrg.io")
_IMG_MAX_BYTES = 5_000_000


def _allowed_image_url(url: str) -> bool:
    """https only, and the parsed hostname must be a Kroger domain. A substring check would let
    `http://169.254.169.254/?kroger.com` through and turn this endpoint into an SSRF proxy."""
    try:
        u = httpx.URL(url)
    except Exception:
        return False
    host = (u.host or "").lower().rstrip(".")
    return u.scheme == "https" and u.port in (None, 443) and any(
        host == d or host.endswith("." + d) for d in _IMG_HOST_SUFFIXES)


@app.get("/api/img")
async def proxy_image(url: str = Query(..., description="Image URL to proxy")):
    """Proxy Kroger product images to avoid CDN referrer/origin blocks."""
    if not _allowed_image_url(url):
        raise HTTPException(400, "Only Kroger image URLs allowed")
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            # Follow redirects by hand so every hop is re-checked against the allowlist
            for _ in range(4):
                resp = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/20100101 Firefox/140.0",
                    "Accept": "image/*",
                })
                if resp.is_redirect and resp.headers.get("location"):
                    url = str(resp.url.join(resp.headers["location"]))
                    if not _allowed_image_url(url):
                        raise HTTPException(400, "Redirect to a non-Kroger URL blocked")
                    continue
                break
            if resp.status_code != 200:
                raise HTTPException(resp.status_code if 400 <= resp.status_code < 600 else 502, "Image fetch failed")
            content_type = resp.headers.get("content-type", "image/jpeg")
            if not content_type.lower().startswith("image/") or len(resp.content) > _IMG_MAX_BYTES:
                raise HTTPException(502, "Upstream did not return an image")
            return StreamingResponse(io.BytesIO(resp.content), media_type=content_type,
                                     headers={"Cache-Control": "public, max-age=86400"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Image proxy error: {e}")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/")
async def root():
    # no-cache: the browser revalidates on every load, so an update or deploy is never hidden
    # behind a cached page from an older version (whose API calls may no longer exist).
    return FileResponse(BASE_DIR / "static" / "index.html", headers={"Cache-Control": "no-cache"})
