# Configuration

## Kroger API credentials

The backend needs a Kroger developer client ID and client secret. Get them at <https://developer.kroger.com/>.

The backend reads them from the first `.env` file it finds, in this order:

1. `backend/.env` (running from source)
2. `%APPDATA%\KrogerLookup\.env` (Windows)
3. `~/.kroger-lookup/.env` (macOS and Linux)

Each file holds two lines:

```
KROGER_CLIENT_ID=your-client-id
KROGER_CLIENT_SECRET=your-client-secret
```

`backend/.env.example` is a template. The desktop app's setup screen writes the file for you. An empty `.env` earlier in the list hides the ones after it, so delete any empty `backend/.env`.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `KROGER_CLIENT_ID` | none | Kroger API client ID. A `.env` file can set it instead. |
| `KROGER_CLIENT_SECRET` | none | Kroger API client secret. |
| `WEB_MODE` | off | `true` runs the hosted build: no deals, setup and session endpoints return 404, the server listens on all interfaces, and the daily budget below applies. |
| `PORT` | `8000` | Port the backend listens on. The desktop app sets its own port. |
| `WEB_DAILY_PRODUCT_CALLS` | `8000` | Web mode only: Kroger product API calls allowed per UTC day. |
| `WEB_DAILY_LOCATION_CALLS` | `1300` | Web mode only: Kroger location API calls allowed per UTC day. |

## Hosting the web app

The root `Dockerfile` builds the web app. It installs the hashed lock file `backend/requirements.txt`, runs as an unprivileged user and starts `python -m kroger_lookup` on port 8000. Run these from the repository root:

```
docker build -t kroger-lookup .
docker run -p 8000:8000 -e KROGER_CLIENT_ID=your-id -e KROGER_CLIENT_SECRET=your-secret kroger-lookup
```

Set the credentials as host environment variables only. In web mode the setup screen is turned off, so visitors can never enter or change credentials.

The hosted app's browser API calls are accepted only from its own site address (CORS, the browser rule that controls which websites may call an API). Change `WEB_ORIGIN` in `backend/kroger_lookup/main.py` if the address changes.

## Kroger API limits

Kroger's free tier allows 10,000 product calls and 1,600 calls per location endpoint per day. A division search uses 2 to 10 location calls. The web app's daily budget stays below these limits; when it runs out, searches return "Daily lookup limit reached" until midnight UTC.
