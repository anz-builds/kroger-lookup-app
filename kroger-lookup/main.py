import os
import time
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Kroger Product Lookup")

_web_mode = os.getenv("WEB_MODE", "").lower() in ("true", "1", "yes")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _web_mode else [
        "https://www.kroger.com",
        "https://kroger.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:18234",
        "http://127.0.0.1:18234",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

CLIENT_ID = os.getenv("KROGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("KROGER_CLIENT_SECRET")
BASE_URL = "https://api.kroger.com/v1"
WEB_MODE = os.getenv("WEB_MODE", "").lower() in ("true", "1", "yes")

TIMEOUT = httpx.Timeout(connect=20.0, read=30.0, write=10.0, pool=5.0)

_token_cache = {"access_token": None, "expires_at": 0}

# Kroger atlas session cookies — harvested from a real browser via Playwright
# Auto-refreshed on startup and on 403 from the atlas API
_atlas_cookies: str = ""
_atlas_laf: str = ""
_atlas_cookies_refreshing: bool = False


def _harvest_cookies_stub() -> list:
    """Cookies handled via manual paste in the UI."""
    return []


async def _playwright_fetch_atlas(url: str, params: list, headers: dict) -> dict:
    """
    Use curl_cffi with Firefox TLS impersonation.
    firefox133 is proven to get 200s from Kroger's atlas API.
    Retries on intermittent HTTP/2 stream resets.
    """
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        # No curl_cffi — fall back to httpx (will likely 403)
        async with httpx.AsyncClient(timeout=ATLAS_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=headers)
        result = {"status": resp.status_code}
        try:
            result["json"] = resp.json()
        except Exception:
            result["text"] = resp.text
        return result

    max_retries = 4
    last_error = None
    for attempt in range(max_retries):
        try:
            async with AsyncSession(impersonate="firefox133") as session:
                resp = await session.get(
                    url, params=params, headers=headers,
                    timeout=30,
                )
            result = {"status": resp.status_code}
            try:
                result["json"] = resp.json()
            except Exception:
                result["text"] = resp.text

            # Retry on 429 rate limit
            if resp.status_code == 429 and attempt < max_retries - 1:
                import asyncio
                wait = 3.0 * (attempt + 1)
                print(f"  Atlas 429 rate limited — retry {attempt+1}/{max_retries} (wait {wait}s)")
                await asyncio.sleep(wait)
                continue

            return result
        except Exception as e:
            last_error = e
            err_str = str(e)
            retryable = any(x in err_str for x in (
                "stream", "INTERNAL_ERROR", "err 2", "reset", "closed cleanly",
            ))
            if retryable and attempt < max_retries - 1:
                import asyncio
                wait = 1.5 * (attempt + 1)
                print(f"  curl_cffi retry {attempt+1}/{max_retries} (wait {wait}s): {err_str[:100]}")
                await asyncio.sleep(wait)
                continue
            # Non-retryable or exhausted retries
            return {"error": f"curl_cffi: {err_str}"}


async def _harvest_atlas_cookies() -> str:
    """
    Read kroger.com cookies from Chrome's local database via browser-cookie3.
    Runs in a thread executor since browser-cookie3 is synchronous.
    """
    global _atlas_cookies, _atlas_cookies_refreshing
    if _atlas_cookies_refreshing:
        return _atlas_cookies

    _atlas_cookies_refreshing = True
    try:
        print("  Reading kroger.com cookies from Chrome profile...")
        cookies = _harvest_cookies_stub()

        if not cookies:
            print("  Warning: no kroger.com cookies found in Chrome — visit kroger.com in Chrome first")
            return _atlas_cookies

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        bm_count = sum(1 for c in cookies if c["name"].startswith("bm_") or c["name"] == "_abck")
        print(f"[OK] Loaded {len(cookies)} kroger.com cookies ({bm_count} Akamai tokens) from Chrome")
        _atlas_cookies = cookie_str
        return cookie_str

    except ImportError as e:
        print(f"  Cookie harvest ImportError: {e}")
        return _atlas_cookies
    except Exception as e:
        import traceback
        print(f"  Cookie harvest failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return _atlas_cookies
    finally:
        _atlas_cookies_refreshing = False


@app.on_event("startup")
async def check_credentials():
    missing = [k for k, v in {
        "KROGER_CLIENT_ID": CLIENT_ID,
        "KROGER_CLIENT_SECRET": CLIENT_SECRET,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)} — check your .env file at {BASE_DIR / '.env'}"
        )
    print(f"[OK] Credentials loaded (CLIENT_ID: {CLIENT_ID[:8]}...)")
    if WEB_MODE:
        print("[OK] Running in WEB_MODE — atlas/deals features disabled")
    else:
        # Harvest Akamai session cookies in background — don't block startup
        asyncio.create_task(_harvest_atlas_cookies())


async def get_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
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
    token = await get_token()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if resp.status_code == 401:
                _token_cache["access_token"] = None
                token = await get_token()
                resp = await client.get(
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


@app.post("/api/atlas-cookies")
async def set_atlas_cookies_manual(request: Request):
    """Accept a raw Cookie header value OR a full PowerShell/curl command.
    Parses Cookie and x-laf-object automatically from a pasted command."""
    global _atlas_cookies, _atlas_laf
    import re
    body = await request.json()
    raw = (body.get("cookies") or "").strip()
    if not raw:
        raise HTTPException(400, "No cookies provided")

    is_powershell = "Invoke-WebRequest" in raw
    is_curl = raw.strip().startswith("curl")

    if is_powershell:
        # ── Extract cookies from PowerShell New-Object System.Net.Cookie lines ──
        cookie_parts = []
        for m in re.finditer(r'New-Object System\.Net\.Cookie\("([^"]+)",\s*"([^"]*)"', raw):
            cookie_parts.append(f"{m.group(1)}={m.group(2)}")
        if cookie_parts:
            _atlas_cookies = "; ".join(cookie_parts)
        else:
            # Fallback: look for Cookie header in $headers hashtable
            cookie_hdr = re.search(r'"[Cc]ookie"\s*=\s*"((?:[^"`]|`.)*)"', raw)
            if cookie_hdr:
                _atlas_cookies = cookie_hdr.group(1).replace('`"', '"')

        # ── Extract x-laf-object ──
        # PowerShell uses backtick (`) as escape char, NOT backslash.
        # Chrome "Copy as PowerShell" produces:  "x-laf-object" = "[{`"modality`":...}]"
        # Old regex used [^"\\]|\\. which stops at the first `" — only captures ~2 chars.
        # Fixed regex: [^"`]|`. matches non-quote-non-backtick OR backtick+anything.
        laf_m = re.search(r'"x-laf-object"\s*=\s*"((?:[^"`]|`.)*)"', raw)
        if laf_m:
            _atlas_laf = laf_m.group(1).replace('`"', '"').replace('`n', '\n').replace('``', '`')
            print(f"  Parsed x-laf-object ({len(_atlas_laf)} chars, first 80: {_atlas_laf[:80]})")
        else:
            _atlas_laf = ""
            print("  Warning: x-laf-object not found in PowerShell command")

    elif is_curl:
        # ── Extract cookies from curl -H 'Cookie: ...' or -b '...' ──
        cookie_m = re.search(r"-[Hb]\s+'[Cc]ookie:\s*([^']+)'", raw) or \
                   re.search(r'-[Hb]\s+"[Cc]ookie:\s*([^"]+)"', raw)
        if cookie_m:
            _atlas_cookies = cookie_m.group(1).strip()

        # ── Extract x-laf-object from curl -H 'x-laf-object: ...' ──
        laf_m = re.search(r"-H\s+'x-laf-object:\s*([^']+)'", raw) or \
                re.search(r'-H\s+"x-laf-object:\s*([^"]+)"', raw)
        if laf_m:
            _atlas_laf = laf_m.group(1).strip()
            print(f"  Parsed x-laf-object from curl ({len(_atlas_laf)} chars)")
        else:
            _atlas_laf = ""
            print("  Warning: x-laf-object not found in curl command")

    else:
        _atlas_cookies = raw
        _atlas_laf = ""

    keys = [c.split("=")[0].strip() for c in _atlas_cookies.split(";") if "=" in c]
    bm = sum(1 for k in keys if k.startswith("bm_") or k == "_abck")
    print(f"  Loaded {len(keys)} cookies ({bm} Akamai), laf={'yes' if _atlas_laf else 'no'}")
    return {"ok": True, "cookieCount": len(keys), "akamaiTokens": bm,
            "source": "powershell" if is_powershell else ("curl" if is_curl else "manual"),
            "hasLaf": bool(_atlas_laf), "lafLength": len(_atlas_laf),
            "lafParsed": bool(_atlas_laf)}


@app.post("/api/atlas-cookies/refresh")
async def refresh_atlas_cookies_endpoint():
    """Trigger a browser-based cookie harvest from kroger.com."""
    cookies = await _harvest_atlas_cookies()
    if cookies:
        keys = [c.split("=")[0].strip() for c in cookies.split(";") if "=" in c]
        return {"ok": True, "cookieCount": len(keys), "source": "browser"}
    return {"ok": False, "message": "Harvest failed — check server logs. Try manual paste instead."}


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


# ── Chrome CDP Cookie Extraction ──

@app.post("/api/cdp/connect")
async def cdp_connect(request: Request):
    """Connect to Chrome via CDP (remote debugging port) and extract Kroger session.
    Chrome must be running with --remote-debugging-port=9333.
    Extracts: all kroger.com cookies + x-laf-object from localStorage."""
    global _atlas_cookies, _atlas_laf
    import json as _j

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    cdp_port = body.get("port", 9333)
    cdp_host = body.get("host", "127.0.0.1")

    # Step 1: Check if CDP is reachable and get tab list
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://{cdp_host}:{cdp_port}/json")
            tabs = resp.json()
    except Exception as e:
        return {"ok": False, "error": "cdp_unreachable",
                "message": f"Cannot reach Chrome on {cdp_host}:{cdp_port}. "
                           f"Launch Chrome with --remote-debugging-port={cdp_port}. Error: {e}"}

    # Step 2: Find a Kroger tab (prefer one, but any tab works for cookies)
    kroger_tab = None
    any_tab = None
    for tab in tabs:
        if tab.get("type") != "page":
            continue
        if not any_tab:
            any_tab = tab
        url = tab.get("url", "")
        if "kroger.com" in url:
            kroger_tab = tab
            break

    target_tab = kroger_tab or any_tab
    if not target_tab or not target_tab.get("webSocketDebuggerUrl"):
        return {"ok": False, "error": "no_tabs",
                "message": f"Found {len(tabs)} items but no usable page tab with WebSocket URL. "
                           "Make sure Chrome has at least one open tab."}

    ws_url = target_tab["webSocketDebuggerUrl"]
    # Fix localhost → 127.0.0.1 to avoid IPv6 issues
    ws_url = ws_url.replace("ws://localhost:", "ws://127.0.0.1:")
    print(f"  CDP: connecting to {ws_url} (tab: {target_tab.get('url', '')[:60]})")

    # Step 3: Connect via WebSocket and extract cookies + LAF
    try:
        import websockets
    except ImportError:
        return {"ok": False, "error": "missing_dep",
                "message": "websockets package not installed. Run: pip install websockets"}

    extracted_cookies = []
    extracted_laf = ""
    msg_id = 1

    try:
        async with websockets.connect(ws_url, max_size=10_000_000) as ws:
            # 3a: Get ALL cookies (not just kroger.com — Chrome returns all)
            await ws.send(_j.dumps({"id": msg_id, "method": "Network.getAllCookies"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            cookie_resp = _j.loads(raw)
            all_cookies = cookie_resp.get("result", {}).get("cookies", [])

            # Filter to kroger.com domain cookies
            kroger_cookies = []
            for c in all_cookies:
                domain = c.get("domain", "")
                if "kroger.com" in domain:
                    kroger_cookies.append(c)

            # Build cookie string
            cookie_parts = []
            for c in kroger_cookies:
                name = c.get("name", "")
                value = c.get("value", "")
                if name:
                    cookie_parts.append(f"{name}={value}")

            if cookie_parts:
                extracted_cookies = cookie_parts
                print(f"  CDP: extracted {len(kroger_cookies)} kroger.com cookies from {len(all_cookies)} total")
            else:
                print(f"  CDP: no kroger.com cookies found in {len(all_cookies)} total cookies")

            # 3b: Extract LAF by intercepting a real atlas request from the Kroger page
            if kroger_tab:
                msg_id += 1
                # Enable network monitoring
                await ws.send(_j.dumps({"id": msg_id, "method": "Network.enable"}))
                await asyncio.wait_for(ws.recv(), timeout=5)

                msg_id += 1
                # Trigger a small atlas request from the page — this forces Chrome to
                # send all the right headers (x-laf-object, x-modality, etc.)
                trigger_js = """
                fetch('/atlas/v1/product/v2/products?filter.verified=true&filter.gtin13s=0001111042545&projections=items.full,offers.compact', {
                    credentials: 'include'
                }).catch(function(){});
                'triggered'
                """
                await ws.send(_j.dumps({
                    "id": msg_id, "method": "Runtime.evaluate",
                    "params": {"expression": trigger_js, "returnByValue": True}
                }))
                await asyncio.wait_for(ws.recv(), timeout=5)

                # Listen for the requestWillBeSent event to capture headers
                import time
                deadline = time.time() + 6
                while time.time() < deadline:
                    try:
                        raw_evt = await asyncio.wait_for(ws.recv(), timeout=3)
                        evt = _j.loads(raw_evt)
                        method = evt.get("method", "")
                        if method == "Network.requestWillBeSent":
                            req_url = evt.get("params", {}).get("request", {}).get("url", "")
                            if "atlas" in req_url and "product" in req_url:
                                req_headers = evt["params"]["request"].get("headers", {})
                                laf_h = req_headers.get("x-laf-object", "")
                                if laf_h and "modality" in laf_h:
                                    extracted_laf = laf_h
                                    print(f"  CDP: captured LAF from live atlas request ({len(extracted_laf)} chars)")
                                break
                    except asyncio.TimeoutError:
                        break

                # Disable network monitoring
                msg_id += 1
                await ws.send(_j.dumps({"id": msg_id, "method": "Network.disable"}))
                try:
                    await asyncio.wait_for(ws.recv(), timeout=2)
                except asyncio.TimeoutError:
                    pass

                if not extracted_laf:
                    print("  CDP: could not capture LAF from network, trying JS fallback")
                    # JS fallback: check localStorage/sessionStorage/document.cookie
                    msg_id += 1
                    js_code = """
                    (function() {
                        // Check localStorage for LAF-like keys
                        try {
                            var keys = Object.keys(localStorage);
                            for (var i = 0; i < keys.length; i++) {
                                var v = localStorage.getItem(keys[i]);
                                if (v && v.indexOf('handoffLocation') !== -1 && v.indexOf('modality') !== -1) {
                                    return v;
                                }
                            }
                        } catch(e) {}
                        // Check sessionStorage
                        try {
                            var keys2 = Object.keys(sessionStorage);
                            for (var i = 0; i < keys2.length; i++) {
                                var v2 = sessionStorage.getItem(keys2[i]);
                                if (v2 && v2.indexOf('handoffLocation') !== -1 && v2.indexOf('modality') !== -1) {
                                    return v2;
                                }
                            }
                        } catch(e) {}
                        return null;
                    })()
                    """
                    await ws.send(_j.dumps({
                        "id": msg_id, "method": "Runtime.evaluate",
                        "params": {"expression": js_code, "returnByValue": True}
                    }))
                    raw2 = await asyncio.wait_for(ws.recv(), timeout=5)
                    laf_resp = _j.loads(raw2)
                    laf_val = laf_resp.get("result", {}).get("result", {}).get("value")
                    if laf_val and isinstance(laf_val, str) and "handoffLocation" in laf_val:
                        extracted_laf = laf_val
                        print(f"  CDP: extracted LAF from storage ({len(extracted_laf)} chars)")

    except asyncio.TimeoutError:
        return {"ok": False, "error": "cdp_timeout",
                "message": "WebSocket command timed out. Chrome may be busy."}
    except Exception as e:
        return {"ok": False, "error": "cdp_error",
                "message": f"CDP WebSocket error: {e}"}

    if not extracted_cookies:
        return {"ok": False, "error": "no_cookies",
                "message": "Connected to Chrome but found no kroger.com cookies. "
                           "Visit kroger.com in Chrome first, then retry."}

    # Step 4: Set the global session
    _atlas_cookies = "; ".join(extracted_cookies)

    # Log key cookie values for debugging
    import re as _re2
    dd_store_val = _re2.search(r'DD_modStore=([^;]+)', _atlas_cookies)
    x_active_val = _re2.search(r'x-active-modality=([^;]+)', _atlas_cookies)
    print(f"  CDP: DD_modStore={dd_store_val.group(1) if dd_store_val else 'NOT FOUND'}")
    print(f"  CDP: x-active-modality={x_active_val.group(1)[:80] if x_active_val else 'NOT FOUND'}")

    # If we got LAF from network/localStorage, use it; otherwise try to build from cookies
    if extracted_laf:
        _atlas_laf = extracted_laf
    else:
        # Try to reconstruct LAF from x-active-modality cookie and DD_modStore
        import re
        from urllib.parse import unquote
        modality_m = re.search(r'x-active-modality=([^;]+)', _atlas_cookies)
        dd_store_m = re.search(r'DD_modStore=([^;]+)', _atlas_cookies)
        if modality_m and dd_store_m:
            try:
                raw_mod = unquote(modality_m.group(1).strip())
                mod_data = _j.loads(raw_mod)
                store_id = dd_store_m.group(1).strip()
                mod_type = mod_data.get("type", "PICKUP")
                loc_id = mod_data.get("locationId", store_id)
                # Build minimal LAF — enough for atlas API headers
                minimal_laf = _j.dumps([{
                    "modality": {
                        "type": mod_type,
                        "handoffLocation": {"storeId": loc_id}
                    },
                    "sources": [{"storeId": loc_id}],
                    "listingKeys": [loc_id]
                }])
                _atlas_laf = minimal_laf
                print(f"  CDP: built minimal LAF from cookies (store={loc_id}, type={mod_type})")
            except Exception as e:
                print(f"  CDP: could not build LAF from cookies: {e}")
                _atlas_laf = ""
        elif dd_store_m:
            # Only DD_modStore available — still build minimal LAF
            store_id = dd_store_m.group(1).strip()
            _atlas_laf = _j.dumps([{
                "modality": {"type": "PICKUP", "handoffLocation": {"storeId": store_id}},
                "sources": [{"storeId": store_id}],
                "listingKeys": [store_id]
            }])
            print(f"  CDP: built minimal LAF from DD_modStore only (store={store_id})")
        else:
            _atlas_laf = ""
            print("  CDP: no modality cookie found, LAF will be empty")

    keys = [c.split("=")[0].strip() for c in _atlas_cookies.split(";") if "=" in c]
    bm = sum(1 for k in keys if k.startswith("bm_") or k == "_abck")
    return {
        "ok": True,
        "cookieCount": len(keys),
        "akamaiTokens": bm,
        "hasLaf": bool(_atlas_laf),
        "lafLength": len(_atlas_laf),
        "source": "cdp",
        "tab": target_tab.get("url", "")[:80],
        "krogerTab": bool(kroger_tab),
    }


@app.get("/api/cdp/status")
async def cdp_status():
    """Quick check: is Chrome's debug port reachable?"""
    cdp_port = 9333
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"http://127.0.0.1:{cdp_port}/json/version")
            data = resp.json()
            return {"reachable": True, "browser": data.get("Browser", "?"),
                    "port": cdp_port}
    except Exception:
        return {"reachable": False, "port": cdp_port}


ATLAS_COUPONS_BASE = "https://www.kroger.com/atlas/v1/savings-coupons/v1/coupons"
ATLAS_PRODUCT_BASE = "https://www.kroger.com/atlas/v1/product/v2/products"
ATLAS_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=5.0, pool=5.0)


def _atlas_headers(location_id: str, upcs: list = None, store_data: dict = None) -> dict:
    """Headers for atlas API.
    Priority for LAF: 1) Full LAF from PowerShell paste  2) Built from store_data  3) Minimal from cookies"""
    import json as _j, re as _re

    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://www.kroger.com/search?query=grocery&searchType=default_search",
        "User-Time-Zone": "America/New_York",
        "X-Kroger-Channel": "WEB",
        "x-call-origin": '{"component":"internal search","page":"internal search"}',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        **( {"Cookie": _atlas_cookies} if _atlas_cookies else {} ),
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


@app.post("/api/deals/batch")
async def fetch_deals_batch(request: Request):
    """
    Fetch deals for a batch of UPCs from Kroger's internal atlas API.
    Uses TWO endpoints:
      1. /atlas/v1/product/v2/products — store promotions (BOGO, sale prices, weekly ad)
      2. /atlas/v1/savings-coupons/v1/coupons — digital coupons (clip-to-card)
    Returns: { "<upc>": [ {"badge": str, "text": str, "value": any, ...}, ... ] }
    """
    body = await request.json()
    upcs = [str(u).strip().zfill(13) for u in body.get("upcs", [])][:50]

    if WEB_MODE:
        return {"_error": "web_mode", "_message": "Deals require the desktop app",
                **{upc: [] for upc in upcs}}

    location_id = (body.get("location_id") or "").strip()
    store_data = body.get("store")  # Full store object from frontend

    if not upcs:
        return {}

    if not _atlas_cookies:
        return {"_error": "no_session", "_message": "No atlas session — paste cookies first",
                **{upc: [] for upc in upcs}}

    headers = _atlas_headers(location_id, upcs, store_data=store_data)
    result = {upc: [] for upc in upcs}
    pricing_data = {}
    import json as _json

    # ── 1. Product promos (BOGO, sale prices) — the main source ──
    product_params = [("filter.gtin13s", upc) for upc in upcs]
    product_params.append(("filter.verified", "true"))
    product_params.append(("projections", "items.full,offers.compact,inventory.projected"))

    try:
        print(f"Fetching product promos for {len(upcs)} UPCs...")
        # Log key headers for debugging
        print(f"  Headers: x-facility-id={headers.get('X-Facility-Id','NONE')} "
              f"x-modality-type={headers.get('x-modality-type','NONE')} "
              f"laf={len(headers.get('x-laf-object',''))} chars "
              f"cookie={len(headers.get('Cookie',''))} chars")
        resp = await _playwright_fetch_atlas(ATLAS_PRODUCT_BASE, product_params, headers)
        if "error" in resp:
            print(f"  Product API error: {resp['error'][:150]}")
        elif resp.get("status") == 200:
            raw = resp["json"]
            print(f"  Product API 200: keys={list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__}")
            promos, atlas_pricing = _parse_product_promos(raw, upcs)
            pricing_data.update(atlas_pricing)
            for upc, deals in promos.items():
                if deals:
                    result[upc].extend(deals)
        elif resp.get("status") == 403:
            print(f"  Product API 403 — session expired")
            return {"_error": "forbidden", "_message": "Session expired (403). Re-paste cookies.",
                    "_status": 403, **{upc: [] for upc in upcs}}
        elif resp.get("status") == 429:
            print(f"  Product API 429 — rate limited. Waiting 3s before coupon call...")
            import asyncio as _aio
            await _aio.sleep(3)
        else:
            body_preview = str(resp.get('text', '') or resp.get('json', ''))[:300]
            print(f"  Product API {resp.get('status')}: {body_preview}")
    except Exception as e:
        print(f"  Product promo error: {e}")

    # Small delay between calls to avoid rate limits
    import asyncio as _aio
    await _aio.sleep(0.5)

    # ── 2. Digital coupons (clip-to-card) — supplementary ──
    coupon_params = [("filter.upc", upc) for upc in upcs]
    coupon_params += [("filter.type", "standard"), ("filter.type", "cash_back")]
    coupon_params.append(("projections", "coupons.full"))

    try:
        print(f"Fetching digital coupons for {len(upcs)} UPCs...")
        resp = await _playwright_fetch_atlas(ATLAS_COUPONS_BASE, coupon_params, headers)
        if "error" in resp:
            print(f"  Coupons API error: {resp['error'][:150]}")
        elif resp.get("status") == 200:
            raw = resp["json"]
            coupons = _parse_atlas_response(raw, upcs)
            for upc, deals in coupons.items():
                if deals:
                    result[upc].extend(deals)
        else:
            body_preview = str(resp.get('text', '') or resp.get('json', ''))[:300]
            print(f"  Coupons API {resp.get('status')}: {body_preview}")
    except Exception as e:
        print(f"  Digital coupon error: {e}")

    matched = sum(1 for v in result.values() if v)
    print(f"Deals total: {matched}/{len(upcs)} UPCs have deals, {len(pricing_data)} with atlas pricing")
    return {**result, "_atlas_pricing": pricing_data}

@app.get("/api/config")
async def get_config():
    """Return app configuration for frontend mode detection."""
    return {"webMode": WEB_MODE}


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "static" / "index.html")


# ── Standalone launch (used by PyInstaller bundled exe) ──
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    host = "0.0.0.0" if WEB_MODE else "127.0.0.1"
    print(f"Starting Kroger Price Lookup on http://{host}:{port} (web_mode={WEB_MODE})")
    uvicorn.run(app, host=host, port=port, log_level="info")
