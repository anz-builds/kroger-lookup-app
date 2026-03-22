# Kroger Price Lookup

A full-featured product search and deal discovery tool for Kroger and its family of banners (Ralphs, Fred Meyer, King Soopers, Harris Teeter, and more). Search products by name or UPC, compare store-specific pricing, and surface hidden deals including BOGO, multi-buy offers, Yellow Tag markdowns, and digital coupons.

Available as a **web app** (product search + pricing) and a **desktop app** (adds deal/coupon data via built-in Kroger login).

> **[Try the Web Demo →](#deployment)** · **[Download Desktop App →](#desktop-app)**

---

## Features

### Product Search
- Search by **product name** or **UPC code** across all Kroger banners
- Multi-word search with local precision filtering
- "Search without store" mode for browsing the full Kroger catalog
- Product details: description, nutrition, ingredients, images, categories

### Store Finder
- Find stores by **ZIP code**, **division number** (25 divisions with autocomplete), or **direct store ID**
- Full store details: address, phone, departments, hours
- Division search covers all Kroger banners: Kroger, Ralphs, Fred Meyer, King Soopers, Smith's, QFC, Dillons, Fry's, Food 4 Less, Harris Teeter, Mariano's, Roundy's, and more
- Internal/HQ test stores automatically filtered out

### Pricing & Deals (Desktop App)
- **Store-specific pricing**: regular price, sale price, per-unit size
- **BOGO** offers with automatic 50% net price calculation
- **Multi-buy offers**: "4/$10" → shows $2.50/each net price
- **Yellow Tag** markdowns with prominent sale price display
- **Digital coupons** from Kroger's clip-to-card system
- **Net price calculation** across all deal types
- Color-coded deal badges: red (BOGO), purple (Multi-Buy), gold (Yellow Tag), green (Coupon)

### User Experience
- **Kroger-themed UI**: actual Kroger SVG logo, Nunito headings, system font body — matches kroger.com's design language
- **First-launch tour**: 5-step onboarding walkthrough with floating tooltips
- **Collapsible sidebar panels** that auto-collapse after selection
- **Out-of-stock detection** with card graying and optional hide toggle
- **Copy UPC** button on every product card
- **Clickable header badge** linking to selected store's Kroger page
- **Re-search nudge** when store changes with results showing

---

## Architecture

```
kroger-lookup/
├── main.py                  # FastAPI backend (API proxy, deal parsing, session management)
├── static/index.html        # React frontend (single-file, CDN-loaded, no build step)
├── requirements.txt         # Full dependencies (desktop)
├── requirements-web.txt     # Slim dependencies (web deployment)
├── .env.example             # Environment variable template
│
├── electron/                # Electron wrapper (desktop app)
│   ├── main.js              # Main process: spawns FastAPI, login window, cookie extraction
│   ├── preload.js           # IPC bridge for main window
│   ├── preload-login.js     # IPC bridge for login window
│   └── package.json         # Electron + electron-builder config
│
├── Dockerfile               # Web deployment (Koyeb/Render/Railway)
├── Procfile                 # Alternative deployment
├── build.bat                # Production build script (PyInstaller + Electron)
└── dev.bat                  # Development mode launcher
```

### How It Works

**Public API** (product search, store finder, pricing):
- Uses the [Kroger Developer API](https://developer.kroger.com/) with OAuth2 client credentials
- Server-side token caching with automatic refresh
- 10,000 calls/day on the free tier

**Atlas API** (deals, coupons, multi-buy offers — desktop app only):
- Accesses Kroger's internal `atlas` API endpoints used by kroger.com
- Authenticates via browser session cookies extracted from the Electron login window
- `curl_cffi` with Firefox TLS impersonation for reliable access
- LAF (Location-Aware Framework) headers built from the user's selected Pickup store

**Web Mode** (`WEB_MODE=true`):
- Disables all atlas/deal features — no `curl_cffi` dependency needed
- Deals panel shows a "Download Desktop App" CTA card
- Tour steps adapt messaging for web visitors
- Slim Docker image with just FastAPI + httpx

---

## Quick Start

### Prerequisites
- Python 3.11+ 
- [Kroger Developer API credentials](https://developer.kroger.com/) (free)

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/kroger-lookup.git
cd kroger-lookup/kroger-lookup

pip install -r requirements.txt
cp .env.example .env
# Edit .env with your KROGER_CLIENT_ID and KROGER_CLIENT_SECRET
```

### Run (Web/Dev Mode)

```bash
cd kroger-lookup
python main.py
# or: uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000)

---

## Desktop App

The desktop app wraps the FastAPI backend in Electron, adding a built-in Kroger login window for deal/coupon access.

### Development Mode

```bash
cd electron
npm install
npm start
```

This launches Electron, which auto-starts the Python backend.

### Build Portable .exe

```bash
# Windows — produces a single portable .exe (~190MB)
build.bat
```

The build script:
1. Bundles the Python backend with PyInstaller → `kroger-backend.exe`
2. Packages everything into an Electron app → portable `.exe`

### Login Flow

1. Click **"Sign in to Kroger"** in the Deals Session panel
2. A browser window opens to kroger.com — log in with your Kroger account
3. **Select your store for Pickup** (not Delivery) — this is required for deal data
4. Click **"Done — Extract Session"** in the blue banner
5. Session is saved between app launches

---

## Deployment

### Koyeb (Recommended — Free Tier)

1. Push to GitHub
2. Go to [app.koyeb.com](https://app.koyeb.com) → Create App → Deploy from GitHub
3. Select your repo — it auto-detects the `Dockerfile`
4. Add environment variables:
   - `KROGER_CLIENT_ID` = your client ID
   - `KROGER_CLIENT_SECRET` = your secret  
   - `WEB_MODE` = `true`
   - `PORT` = `8000`
5. Deploy

### Other Platforms

**Render**: Create a Web Service, point to your repo, set `WEB_MODE=true` in env vars.

**Docker (anywhere)**:
```bash
docker build -t kroger-lookup .
docker run -p 8000:8000 \
  -e KROGER_CLIENT_ID=your_id \
  -e KROGER_CLIENT_SECRET=your_secret \
  -e WEB_MODE=true \
  kroger-lookup
```

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/locations?zip_code=45202&radius=10` | Search stores near a ZIP |
| `GET /api/locations/{locationId}` | Get store details by ID |
| `GET /api/locations/by-division/014` | List all stores in a division |
| `GET /api/products?term=doritos&location_id=01400929` | Search by keyword |
| `GET /api/products?upc=0002840051777&location_id=...` | Search by UPC |
| `POST /api/deals/batch` | Fetch deals for UPC batch (desktop only) |
| `GET /api/config` | App configuration (web mode detection) |
| `GET /api/atlas-cookies/status` | Session status |

---

## Tech Stack

**Backend**: Python · FastAPI · httpx · curl_cffi · uvicorn  
**Frontend**: React 18 (CDN) · Babel (in-browser JSX) · Single-file SPA  
**Desktop**: Electron · PyInstaller · Chrome DevTools Protocol  
**Deployment**: Docker · Koyeb  
**APIs**: Kroger Public API (OAuth2) · Kroger Atlas API (browser session)  
**Design**: Nunito (Google Fonts) · Kroger SVG logo · System font stack

---

## Notes

- Kroger API free tier allows **10,000 calls/day** — more than enough for personal use
- Deal data (atlas API) requires a Kroger account and is only available in the desktop app
- The app filters out internal Kroger HQ/test stores (1014 Vine St, Cincinnati)
- Fuel stations are flagged in store lists (no dedicated store page)
- `curl_cffi` is only required for the desktop app — web deployment uses httpx only

## License

MIT
