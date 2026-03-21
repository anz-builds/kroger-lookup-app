# Kroger Price Lookup

A local web UI for searching Kroger products by description or UPC, with live pricing by store.

## Setup

```bash
cd kroger-lookup
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your CLIENT_ID and CLIENT_SECRET
```

## Run

```bash
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000

## Usage

1. **Find Stores** — Enter a ZIP code and search radius to list nearby Kroger family stores
2. **Select a Store** — Click a store to scope pricing to that location (optional but required for price data)
3. **Search Products** — Search by product description or exact UPC; results show price, promo price, brand, categories, and UPC

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/locations?zip_code=45202&radius=10` | Search stores near a ZIP |
| `GET /api/products?term=milk&location_id=...` | Search by keyword |
| `GET /api/products?upc=001111060903&location_id=...` | Search by UPC |
| `GET /api/products/{productId}?location_id=...` | Get single product |

## Notes

- Credentials stay server-side; OAuth tokens are cached in memory and auto-refreshed
- The Kroger Products API allows 10,000 calls/day on the free tier
- Price data requires a `location_id`; without one you still get product metadata (brand, UPC, categories, images)
