# Kroger Price Lookup

Kroger Price Lookup searches products and stores across Kroger and its banners (Ralphs, Fred Meyer, King Soopers, Smith's, QFC and others). Search by product name or UPC, pick a store, and see that store's regular and sale prices.

The desktop app also shows the store's current deals for each product: BOGO, multi-buy offers such as "4 for $10", Yellow Tag markdowns and digital coupons. Kroger's public API doesn't include these, so the desktop app reads them from your own signed-in kroger.com session.

The app comes in two forms:

- **Web app:** product search, store finder and store prices. Try it at <https://p01--kroger-lookup--xrzr292k2mfz.code.run>.
- **Desktop app (Windows and macOS):** everything in the web app, plus deals. Download it from the [Releases page](https://github.com/anz-builds/kroger-lookup-app/releases).

## Examples

- Search "coffee" without a store to browse Kroger's catalog.
- Pick a store by ZIP code, division or store ID, then search by UPC (for example `0061124736761`) to see that store's price and any deals.
- In the desktop app, a card for a multi-buy deal shows the price per item, for example "Save $2.00 each (buy 3+)" and "Net: $18.99 each when you buy 3".

## Nomenclature

- **UPC:** the product barcode number. The app pads it to 13 digits, for example `0002840051777`.
- **Store ID (locationId):** an 8-digit Kroger store number: a 3-digit division plus a 5-digit store, for example `01400929`.
- **Division:** a Kroger regional business unit, such as `014` (Cincinnati). One division can include several banners.
- **Banner:** a store brand owned by Kroger, such as Ralphs or Fred Meyer.
- **Public API:** Kroger's official developer API at `api.kroger.com`. It provides products, prices and stores.
- **Atlas API:** the internal API that kroger.com itself uses. It provides deals and coupons, and it only answers requests from a signed-in kroger.com session.
- **Pickup store:** the store you choose for pickup on kroger.com. Deals need a Pickup store; a Delivery address doesn't work.
- **Yellow Tag:** Kroger's in-store markdown price.
- **Web mode:** the hosted build. It has no deals and never accepts credentials or sessions from visitors.

## Prerequisites

- [Python 3.13](https://www.python.org/downloads/)
- [Node.js 22.12 or later](https://nodejs.org/) with npm, for the desktop app
- [uv](https://docs.astral.sh/uv/), only to change dependencies
- A free Kroger developer account with a client ID and client secret, from <https://developer.kroger.com/>

## Getting started

These steps run the desktop app from source on Windows. For macOS, use `.venv/bin/` instead of `.venv\Scripts\`.

1. Clone the repository:

   ```
   git clone https://github.com/anz-builds/kroger-lookup-app.git
   cd kroger-lookup-app
   ```

2. Create the Python environment for the backend:

   ```
   cd backend
   python -m venv .venv
   .venv\Scripts\pip install --require-hashes -r requirements-dev.txt
   cd ..
   ```

3. Install the desktop app's dependencies and start it:

   ```
   cd electron
   npm install
   npm start
   ```

   The first start downloads Electron, which takes about a minute.

4. On the setup screen, enter your Kroger client ID and client secret. The app saves them to `%APPDATA%\KrogerLookup\.env` (macOS: `~/.kroger-lookup/.env`).

5. To see deals, click **Sign in to Kroger** in the Deals Session panel. Sign in on kroger.com, choose your store for **Pickup**, then click **Done — Extract Session** in the blue banner.

To run only the backend in a browser instead, run `.venv\Scripts\python -m kroger_lookup` from `backend/`, then open <http://localhost:8000>. Deals need the desktop app.

## Configure and deploy

- **Settings and credentials:** see [docs/configuration.md](docs/configuration.md).
- **Building the Windows and macOS apps:** see [docs/building.md](docs/building.md).
- **Hosting the web app:** the root `Dockerfile` builds it. Set `KROGER_CLIENT_ID` and `KROGER_CLIENT_SECRET` as environment variables on the host. See [docs/configuration.md](docs/configuration.md).
- **API reference:** see [docs/api.md](docs/api.md).

## Testing

Run the backend tests from `backend/`:

```
.venv\Scripts\python -m pytest
```

The tests make no calls to Kroger.

## More information

- [Kroger developer documentation](https://developer.kroger.com/documentation)
- The project layout comes from the [project-template](https://github.com/anz-builds/project-template) Copier template (`base` and `electron-python` layers).

## Support

Open an issue on [GitHub](https://github.com/anz-builds/kroger-lookup-app/issues).

## Contributing

Open an issue to discuss a change before sending a pull request. Run the tests before you send it.

## Licence

MIT
